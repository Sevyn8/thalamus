-- ============================================================================
-- Enable ONE analysis for ONE tenant in Synapse's shadow mode.
--
-- ----------------------------------------------------------------------------
-- THIS FILE IS NOT PART OF THE NUMBERED SETUP SEQUENCE, AND THAT IS THE POINT
-- ----------------------------------------------------------------------------
-- sql/01..04 are ONE-TIME ENVIRONMENT SETUP: extensions, then grants, run once
-- per environment in the hard dependency order the README lays out, with a
-- "steps 1-5 completed" status line against it. They are idempotent because
-- GRANT and CREATE EXTENSION repeat harmlessly.
--
-- Provisioning is not that. It happens PER TENANT, on the day a customer is
-- enabled, forever, and a fresh environment has no tenants to enable at all.
-- Numbering this `05_` would put a recurring per-customer operation inside a
-- bootstrap checklist and imply that setting up an environment means running it,
-- which is false and would eventually mean someone provisions a tenant into a
-- brand-new database because the runbook said step 5.
--
-- So it lives here, unnumbered, for discoverability, and the README's numbered
-- list is deliberately left alone.
--
-- ----------------------------------------------------------------------------
-- WHY A FILE AND NOT AN ALEMBIC MIGRATION
-- ----------------------------------------------------------------------------
-- Enabling a tenant for an analysis is an OPERATIONAL FACT ABOUT A CUSTOMER. It
-- changes without a release, and that is exactly the argument that put provision
-- in a table rather than in code (see synapse/core/provision.py: the
-- envelope/selection split). A data migration would drag it back into the
-- release cycle by the back door — enabling a customer would need a version bump,
-- a deploy, and a chain that can never be re-run for the next customer.
--
-- ----------------------------------------------------------------------------
-- WHY THE VALUES ARE psql VARIABLES AND NOT EDITED INTO THIS FILE
-- ----------------------------------------------------------------------------
-- The PROCEDURE belongs in git. The CUSTOMER does not.
--
-- Editing the tenant id in place and committing turns git history into a
-- customer registry, and makes checking out an old revision a thing that can
-- re-enable somebody. Editing it and NOT committing leaves the working tree
-- dirty until the next `git checkout` silently discards it. Passing the values
-- with -v avoids both: the file is constant, the run is recorded in the shell,
-- and nothing about a customer is committed.
--
-- ----------------------------------------------------------------------------
-- RUN AS: THE OWNER OF THE synapse SCHEMA
-- ----------------------------------------------------------------------------
--   STAGING : `postgres` (Synapse's Alembic runs as postgres, so it owns synapse)
--   LOCAL   : `ithina_dis_admin`
--
-- NO RUNTIME ROLE CAN DO THIS, deliberately. Migration 0003 grants nothing on
-- synapse.provision to synapse_writer and SELECT-only to synapse_reader, so a
-- bug in the orchestrator cannot enable a customer. Getting the role wrong here
-- fails loudly with 'permission denied for table provision'.
--
-- WHEN: after Synapse's Alembic has reached 0003.
--
-- ----------------------------------------------------------------------------
-- THE INVOCATION
-- ----------------------------------------------------------------------------
--   psql "host=127.0.0.1 dbname=thalamus user=postgres" \
--     -v tenant_id="'00000000-0000-0000-0000-000000000000'" \
--     -v analysis_id="'dead_stock'" \
--     -v tz="'Asia/Kolkata'" \
--     -f provision_analysis.sql
--
-- NOTE THE DOUBLE QUOTING. psql's -v does no quoting of its own, so the SQL
-- string literal quotes have to be inside the shell argument. Getting it wrong
-- fails with a syntax error at the variable, not with a wrong value silently
-- inserted.
--
-- ----------------------------------------------------------------------------
-- WHAT IS DELIBERATELY NOT A VARIABLE: cadence AND rung
-- ----------------------------------------------------------------------------
-- Both are hardcoded below, and this is a safety property rather than a
-- simplification.
--
-- `rung` is hardcoded to 'shadow' because shadow is the ONLY rung anything
-- implements — there is no delivery of any kind — and because the envelope
-- check (a provision may not exceed its analysis's declared max_rung) runs when
-- the ORCHESTRATOR LOADS the table, where it refuses the WHOLE ENUMERATION
-- rather than one row. One mistyped rung would therefore stop the sweep for
-- EVERY tenant, not just the one being enabled. A value that cannot be typed
-- cannot be mistyped.
--
-- `cadence` is hardcoded to 'daily' for the smaller version of the same reason:
-- it is the only member of the enum, so a variable could only ever be wrong.
--
-- When a second rung or cadence genuinely exists, they become variables here and
-- the pre-flight check below grows a line. Not before.
--
-- ----------------------------------------------------------------------------
-- THE TIMEZONE IS THE TENANT'S REPORTING ZONE
-- ----------------------------------------------------------------------------
-- IANA name. It decides what "today" means for this tenant's runs, and it feeds
-- every action's as_of, which sits inside an append-only idempotency index — so
-- it cannot be revised after real rows exist without re-keying a log that cannot
-- be re-keyed. It is NOT identity_mirror.stores.timezone, which is per STORE and
-- a different fact; a tenant spanning zones has several store zones and one
-- reporting zone. An unresolvable zone is refused by a trigger.
--
-- Idempotent: ON CONFLICT DO NOTHING. Re-running never re-enables a tenant that
-- was deliberately disabled, and never overwrites a timezone. See the bottom of
-- this file for how to do either of those on purpose.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- EVERY STATEMENT BELOW RUNS UNDER app.user_type='PLATFORM'. THIS IS THE
-- CONVENTION, NOT A JUDGEMENT ABOUT THIS FILE.
-- ----------------------------------------------------------------------------
-- Every table this file touches — synapse.provision, identity_mirror.tenants,
-- canonical.store_sku_current_position — is FORCE ROW LEVEL SECURITY. Without
-- app.user_type set, a read returns ZERO ROWS AND NO ERROR, for the owner, and
-- for Cloud SQL's `postgres`, which is NOSUPERUSER NOBYPASSRLS like anything
-- else. FORCE means owning the table buys nothing.
--
-- This trap has now bitten four hand-written queries in this repo, every one of
-- them written by someone who had already documented it elsewhere in the same
-- repo. Knowing about it is demonstrably not enough, so it is structural here:
-- the file opens with the set_config and the whole thing is one transaction.
--
-- app.tenant_id IS ALSO SET, and it is not optional either. The policy's
-- WITH CHECK is `tenant_id = NULLIF(current_setting('app.tenant_id',true),'')::uuid`
-- — PLATFORM widens READS only. With the tenant GUC unset the INSERT below fails
-- with 'new row violates row-level security policy for table "provision"'. That
-- is a real failure this file had, invisible on a local devbox because
-- ithina_dis_admin is a SUPERUSER and bypasses RLS entirely.
--
-- Both are transaction-local (`true`), so they end at COMMIT and leak nothing
-- into the session. Same shape as migration 0002.


BEGIN;

SELECT set_config('app.user_type', 'PLATFORM', true);
SELECT set_config('app.tenant_id', :tenant_id, true);


-- ----------------------------------------------------------------------------
-- PRE-FLIGHT — ENFORCED, not a comment someone is trusted to have run
-- ----------------------------------------------------------------------------
-- The two failure modes are reported SEPARATELY because they are not the same
-- problem and the fix differs:
--
--   TENANT DOES NOT EXIST  -> a mistyped UUID. RAISES, so the transaction aborts
--                             and nothing is provisioned. This is the case the
--                             pre-flight exists for, and it is the one that is
--                             otherwise INVISIBLE: the row would insert, the
--                             orchestrator would enumerate it, resolve it, find
--                             no rows and record a perfectly healthy run with
--                             zero actions, every day, forever. Nothing goes red.
--
--   TENANT EXISTS, NO ROWS -> legitimate if ingestion has not happened yet, so it
--                             WARNS and proceeds. Enabling ahead of data is a
--                             real thing to want; a silent zero is not.
DO $preflight$
DECLARE
    v_tenant    uuid := NULLIF(current_setting('app.tenant_id', true), '')::uuid;
    v_name      text;
    v_positions bigint;
BEGIN
    -- Reads the GUC rather than the psql variable on purpose: psql does not
    -- interpolate :variables inside a dollar-quoted body, so a naive :tenant_id
    -- in here would be sent to the server literally.
    IF v_tenant IS NULL THEN
        RAISE EXCEPTION 'app.tenant_id is not set; -v tenant_id was missing or unquoted';
    END IF;

    SELECT name INTO v_name
      FROM identity_mirror.tenants
     WHERE tenant_id = v_tenant;

    IF v_name IS NULL THEN
        RAISE EXCEPTION
            'tenant % is not in identity_mirror.tenants. Either the UUID is mistyped, or '
            'mirror-sync has not yet mirrored this tenant. NOT provisioning: an unknown tenant '
            'produces a healthy-looking run with zero actions every day and never goes red',
            v_tenant;
    END IF;

    SELECT count(*) INTO v_positions
      FROM canonical.store_sku_current_position
     WHERE tenant_id = v_tenant;

    RAISE NOTICE 'tenant % is "%", with % canonical positions', v_tenant, v_name, v_positions;

    IF v_positions = 0 THEN
        RAISE WARNING
            'tenant "%" has NO canonical positions. Provisioning anyway - this is correct if '
            'ingestion is still to come, and every run until then will legitimately produce '
            'nothing. If you expected data, stop and check ingestion before trusting the runs',
            v_name;
    END IF;
END
$preflight$;


-- ----------------------------------------------------------------------------
-- The provision itself
-- ----------------------------------------------------------------------------
INSERT INTO synapse.provision (
    tenant_id, analysis_id, cadence, rung, timezone, enabled_at
)
VALUES (
    CAST(:tenant_id AS uuid),
    :analysis_id,
    'daily',    -- not a variable; see the header
    'shadow',   -- not a variable; see the header
    :tz,
    now()       -- the start of the attribution window, stamped once and never edited
)
ON CONFLICT ON CONSTRAINT pk_provision DO NOTHING;


-- Report what is now true for this tenant, so the run is not a silent success.
-- Readable here because the PLATFORM GUC above is still in force.
--
-- A row with a disabled_at means ON CONFLICT suppressed the insert and the pair
-- was already provisioned AND DISABLED — re-running this file does not re-enable
-- anything, deliberately. See the footer.
SELECT tenant_id, analysis_id, cadence, rung, timezone, enabled_at, disabled_at
  FROM synapse.provision
 WHERE tenant_id = CAST(:tenant_id AS uuid)
   AND analysis_id = :analysis_id;

COMMIT;


-- ----------------------------------------------------------------------------
-- VERIFY (after COMMIT)
-- ----------------------------------------------------------------------------
--
-- 1. THE ROW IS VISIBLE AT ALL. The file printed it already; this is how to look
--    again later. synapse.provision is FORCE ROW LEVEL SECURITY, so a bare SELECT
--    returns ZERO ROWS whatever the truth — including for the owner, and for
--    Cloud SQL's `postgres`, which is NOSUPERUSER NOBYPASSRLS like anything else.
--    Set the GUC or the answer is meaningless:
--
--      BEGIN;
--        SELECT set_config('app.user_type','PLATFORM',true);
--        SELECT tenant_id, analysis_id, rung, timezone FROM synapse.provision;
--      ROLLBACK;
--
-- 2. THE ORCHESTRATOR AGREES. The real check is a dry run, which writes nothing:
--
--      SYNAPSE_READER_URL=... cd dis && \
--        uv run python -m synapse.orchestrator --dry-run
--      -> one line per provisioned pair, with the slot it would use. Confirm the
--         SLOT is the date you expect in the tenant's own zone — that is the
--         timezone column doing its job, and the cheapest place to catch a wrong
--         one is before any action carries it.
--
-- ----------------------------------------------------------------------------
-- THE TWO THINGS THIS FILE DELIBERATELY WILL NOT DO
-- ----------------------------------------------------------------------------
--
-- DISABLE a tenant. One statement, and it preserves the window rather than
-- deleting the row, because enabled_at is the attribution denominator:
--
--   UPDATE synapse.provision SET disabled_at = now()
--    WHERE tenant_id = CAST(:tenant_id AS uuid) AND analysis_id = :analysis_id;
--
-- RE-ENABLE a tenant that was disabled. This one is not a one-liner on purpose:
-- the table holds ONE window per (tenant, analysis), so clearing disabled_at
-- LOSES THE FACT THAT THERE WAS A GAP and the denominator for that period
-- silently becomes wrong. Synapse's provision DDL names this limitation and
-- names its trigger: the first real disable is when the append-only enablement
-- history gets built. If you are about to run this, that moment has arrived.
--
--   UPDATE synapse.provision SET disabled_at = NULL, enabled_at = now()
--    WHERE tenant_id = CAST(:tenant_id AS uuid) AND analysis_id = :analysis_id;
-- ============================================================================
