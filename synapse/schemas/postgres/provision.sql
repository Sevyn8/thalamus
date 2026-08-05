-- ============================================================================
-- synapse.provision — WHICH tenants have WHICH analyses enabled.
--
-- The SELECTION half of the envelope/selection split. The ENVELOPE — how far an
-- action from a given analysis may travel, ever, for anyone — is declared in code
-- on AnalysisDeclaration.max_rung, where changing it is a reviewed diff. This table
-- holds what has been CHOSEN for a tenant, which is an operational fact about a
-- customer and changes without a release. A provision naming a rung above its
-- declaration's max_rung is refused when it is LOADED (see
-- synapse/persistence/provision_postgres.py), so an over-privileged row never
-- reaches an orchestrator.
--
-- This is the source of truth for the DDL; the migration applies it verbatim.
--
-- ----------------------------------------------------------------------------
-- THE TIMEZONE COLUMN IS NOT A SECOND SOURCE OF TRUTH
-- ----------------------------------------------------------------------------
-- identity_mirror.stores.timezone already exists and is PER STORE. This column is
-- PER TENANT and is a DIFFERENT FACT: the tenant's REPORTING timezone, the one that
-- decides what "today" means for a run that spans the whole estate.
--
-- They are not derivable from one another and MUST NOT be checked against one
-- another. A tenant with stores in Mumbai and Dubai has two store timezones and one
-- reporting timezone, and a run has to pick a single day boundary or it cannot
-- produce one coherent as_of for the tenant. Reconciling the two would force a
-- tenant spanning zones to be incoherent in exactly the case this column exists for.
--
-- There is deliberately no FK and no cross-check to identity_mirror. Synapse holds
-- no foreign key into any DIS schema (see actions.sql), and this column would be the
-- worst place to start: mirror-sync owns those rows and a store timezone changing
-- must not silently re-date a tenant's analytics history.
--
-- ----------------------------------------------------------------------------
-- WHY THE TIMEZONE IS VALIDATED BY A TRIGGER AND NOT A CHECK
-- ----------------------------------------------------------------------------
-- A bad zone is SILENT: it does not fail a run, it shifts every slot by some hours
-- and mis-stamps every action's as_of — which sits inside an append-only idempotency
-- index and cannot be re-keyed afterwards. So the invalid row must be impossible,
-- not detectable, the same argument as actions.sql's generated columns.
--
-- A CHECK constraint cannot do it: validating a zone means consulting
-- pg_timezone_names, CHECK constraints must be IMMUTABLE, and a lookup against a
-- catalogue view is not. `now() AT TIME ZONE <bad>` raises, so a BEFORE INSERT OR
-- UPDATE trigger is the only in-database mechanism available. Python validates the
-- same thing in Provision.__post_init__ for rows built without touching this table.
--
-- ----------------------------------------------------------------------------
-- ENABLEMENT HISTORY: ONE WINDOW PER PAIR, AND THE LIMIT IS NAMED
-- ----------------------------------------------------------------------------
-- enabled_at exists because an attribution study needs a DENOMINATOR — how many
-- tenant-days were observed — and that cannot be reconstructed from a system that
-- records only "enabled". Same class as the holdout arm: free today, impossible
-- afterwards.
--
-- The primary key is (tenant_id, analysis_id), so this table holds ONE window per
-- pair: disabling sets disabled_at, and RE-ENABLING THE SAME PAIR OVERWRITES THE
-- FIRST WINDOW. A tenant switched off and on again loses the fact that there was a
-- gap, and the denominator for that period silently becomes wrong.
--
-- That is a real limitation and it is accepted here rather than papered over. The
-- fix is an append-only enablement-history table, which is a second table with its
-- own trigger and its own reader for a case that has never happened — nothing has
-- been disabled, because nothing has yet been enabled. THE TRIGGER FOR BUILDING IT
-- IS THE FIRST DISABLE. At that moment the gap becomes real and the history has to
-- start; before it, the table would be describing behaviour the system has not had.
-- ============================================================================


CREATE TABLE IF NOT EXISTS synapse.provision (
    tenant_id           UUID                        NOT NULL,
    analysis_id         TEXT COLLATE "C"            NOT NULL,

    -- How often this pair is due. Text rather than a native enum, matching actions.sql:
    -- a CHECK is alterable in one migration where an enum needs ALTER TYPE and is
    -- awkward to narrow again.
    cadence             TEXT COLLATE "C"            NOT NULL,

    -- The autonomy rung CHOSEN for this tenant. Bounded above by the analysis's
    -- declared max_rung, which is enforced in the loader rather than here: this table
    -- cannot see a Python declaration, and encoding a per-analysis ceiling in SQL
    -- would be a second copy of it, free to disagree.
    rung                TEXT COLLATE "C"            NOT NULL,

    -- The tenant's REPORTING timezone (IANA). See the header: not the store column,
    -- not derivable from it, not checked against it.
    timezone            TEXT COLLATE "C"            NOT NULL,

    -- The start of the attribution window. The whole reason this table exists now
    -- rather than when there is a console to edit it.
    enabled_at          TIMESTAMPTZ                 NOT NULL,
    -- NULL means active. See the header for the one-window limitation.
    disabled_at         TIMESTAMPTZ                 NULL,

    CONSTRAINT pk_provision PRIMARY KEY (tenant_id, analysis_id),

    CONSTRAINT ck_provision_analysis_named
        CHECK (length(analysis_id) > 0),

    -- The vocabularies, mirroring synapse.core.slot.Cadence and
    -- synapse.core.provision.Rung. Adding a member is a migration, deliberately:
    -- a new cadence or a new rung is not a configuration change.
    CONSTRAINT ck_provision_cadence
        CHECK (cadence IN ('daily')),
    CONSTRAINT ck_provision_rung
        CHECK (rung IN ('shadow', 'suggest')),

    CONSTRAINT ck_provision_timezone_present
        CHECK (length(timezone) > 0),

    -- A window that closes before it opens is not a window.
    CONSTRAINT ck_provision_window_ordered
        CHECK (disabled_at IS NULL OR disabled_at >= enabled_at)
);


-- ----------------------------------------------------------------------------
-- The timezone must RESOLVE. See the header for why this is a trigger.
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION synapse.provision_timezone_resolves()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    -- Raises 'time zone "..." not recognized' for anything Postgres cannot resolve.
    PERFORM now() AT TIME ZONE NEW.timezone;
    RETURN NEW;
EXCEPTION
    WHEN invalid_parameter_value OR undefined_object THEN
        -- `%` is RAISE's ONLY placeholder. `%L` is a format() specifier and RAISE does not
        -- understand it: it substitutes the `%` and prints the `L`, which produced
        -- 'timezone Mars/Olympus_MonsL does not resolve' and read like a mangled value.
        RAISE EXCEPTION
            'synapse.provision.timezone "%" does not resolve. Every slot, and therefore every '
            'action as_of, is computed in this zone; an unresolvable one would shift them '
            'silently rather than fail', NEW.timezone
            USING ERRCODE = 'invalid_parameter_value';
END;
$$;

DROP TRIGGER IF EXISTS trg_provision_timezone_resolves ON synapse.provision;
CREATE TRIGGER trg_provision_timezone_resolves
    BEFORE INSERT OR UPDATE OF timezone ON synapse.provision
    FOR EACH ROW
    EXECUTE FUNCTION synapse.provision_timezone_resolves();


-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------

-- The orchestrator's only query: every ACTIVE provision, across all tenants. Partial
-- on disabled_at IS NULL because that is the enumeration, and a disabled row should
-- not cost anything to skip.
CREATE INDEX IF NOT EXISTS ix_provision_active
    ON synapse.provision (analysis_id, tenant_id)
    WHERE disabled_at IS NULL;


-- ----------------------------------------------------------------------------
-- RLS: the same two-GUC policy as canonical and synapse.actions.
--
-- THE ORCHESTRATOR READS THIS AS PLATFORM, which is what the second USING branch is
-- for. It must enumerate ACROSS tenants — that is the whole job — and then resolve
-- each tenant under TENANT scope. dis_rls.rls_platform_session(engine, None) is
-- exactly that posture: see-all reads, writes nothing, because the tenant GUC is set
-- to '' and NULLIF maps it to NULL so WITH CHECK matches no row.
--
-- FORCE, so the owner is subject to it too. Note the consequence, which has already
-- cost one investigation on synapse.actions: a bare `SELECT count(*)` in psql
-- returns 0 here whatever the truth. Set app.user_type='PLATFORM' before looking.
-- ----------------------------------------------------------------------------
ALTER TABLE synapse.provision ENABLE ROW LEVEL SECURITY;
ALTER TABLE synapse.provision FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON synapse.provision;
CREATE POLICY tenant_isolation
    ON synapse.provision
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        OR current_setting('app.user_type', true) = 'PLATFORM'
    )
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);


COMMENT ON TABLE synapse.provision IS
'WHICH tenants have WHICH analyses enabled, at what cadence and autonomy rung. The SELECTION half; the ENVELOPE (max_rung) is declared in code on AnalysisDeclaration and enforced by the loader.';
COMMENT ON COLUMN synapse.provision.timezone IS
'The TENANT''s reporting timezone (IANA), which decides what "today" means for a run. NOT identity_mirror.stores.timezone, which is per STORE and a different fact; deliberately not checked against it, because a tenant spanning zones has several store zones and one reporting zone.';
COMMENT ON COLUMN synapse.provision.enabled_at IS
'Start of the attribution window. Recorded now because a denominator (tenant-days observed) cannot be reconstructed later.';
COMMENT ON COLUMN synapse.provision.disabled_at IS
'NULL means active. One window per (tenant, analysis): re-enabling overwrites the previous window. An append-only enablement history is deferred until the first disable.';
