-- ============================================================================
-- synapse_provisioner grants: the console's ENABLEMENT credential (slice 5e).
--
-- THE FOURTH SYNAPSE ROLE, and the fourth time the same argument has been made:
-- what a process can do is bounded by its GRANT, not by its code path.
--
--   synapse_reader      SELECT on two canonical tables, identity_mirror, and
--                       synapse.actions / provision / run / action_events.
--   synapse_writer      the ORCHESTRATOR. INSERT on synapse.actions, the run
--                       state machine, nothing on provision.
--   synapse_lifecycle   the console's alert decisions. INSERT on
--                       synapse.action_events and nothing else (slice 5d).
--   synapse_provisioner THIS FILE. Enablement, and nothing else.
--
-- ----------------------------------------------------------------------------
-- WHAT THIS ROLE HOLDS, STATED HONESTLY
-- ----------------------------------------------------------------------------
-- INSERT on synapse.provision, PLUS THE TWO SELECTS ITS PRE-FLIGHT CANNOT RUN
-- WITHOUT.
--
-- The shorter sentence "INSERT on synapse.provision and nothing else" was the
-- intent and it is not achievable, because the pre-flight is the point of the
-- write. provision_analysis.sql enforces two checks before it inserts:
--
--   FATAL : the tenant is in identity_mirror.tenants. An unknown tenant UUID
--           inserts fine, enumerates fine, and produces a healthy run with zero
--           actions every day for ever. Nothing goes red. This check is the
--           entire reason the procedure exists.
--   WARN  : the tenant has canonical positions. Zero is legitimate before
--           ingestion and is worth saying out loud.
--
-- Both must run INSIDE the same transaction as the INSERT or they are advice
-- rather than a gate, and a role holding INSERT alone gets
-- 'permission denied for table tenants' (SQLSTATE 42501) on the first one.
--
-- SO THE ROLE IS WIDENED BY EXACTLY TWO SELECTS, AND NO MORE. Both are already
-- held by synapse_reader (sql/03 lines 150 and 206), so this introduces no new
-- privilege class into the system: it is an existing read posture attached to a
-- second identity. What the role still cannot do is the part that matters:
--
--   - it cannot read synapse.actions, synapse.action_events or synapse.run
--   - it cannot read canonical.store_sku_sale_events or identity_mirror.stores
--   - it cannot UPDATE, DELETE or TRUNCATE anything, anywhere, including
--     synapse.provision itself, so it cannot DISABLE a tenant or edit a
--     timezone. Enablement is one direction only, at the database.
--   - it cannot SELECT synapse.provision, so it cannot read back what it wrote.
--     That is the same property sql/04 states for synapse_writer, it is correct,
--     and it is why the console reads the three enablement states back through
--     synapse_reader.
--
-- THAT LAST ONE COST A DAY, AND THE CORRECTION IS THE POINT OF THIS PARAGRAPH.
-- This header used to say the role "cannot observe whether its own ON CONFLICT
-- DO NOTHING was suppressed". THERE IS NO LONGER AN ON CONFLICT, and the reason
-- is this very grant: ON CONFLICT has to READ the arbiter index to detect the
-- conflict, and that read needs SELECT. Every enable through the console failed
-- with `permission denied for table provision` from the day 5e deployed until
-- 2026-08-10. Isolated as this role, with app.user_type='TENANT' set: the plain
-- INSERT SUCCEEDS, the same INSERT plus ON CONFLICT ON CONSTRAINT pk_provision
-- DO NOTHING is DENIED.
--
-- WHAT REPLACED IT: a plain INSERT, with the duplicate caught in Python on
-- SQLSTATE 23505 matched together with the constraint name pk_provision. The
-- PRIMARY KEY still enforces uniqueness, so re-running still cannot resurrect a
-- disabled pair; only the mechanism that REPORTS a duplicate moved, from SQL to
-- an exception. The endpoint answers 200 with already_provisioned rather than
-- pretending a row appeared.
--
-- GRANTING SELECT WAS THE OTHER AVAILABLE FIX AND IT WAS REFUSED. It would have
-- bought back one SQL clause by falsifying the property this file argues for
-- over four sections, and the role would have gained the ability to read every
-- customer's enablement configuration. A syntax choice is not worth a widened
-- credential. The write path now knows MORE than it did before, not less.
--
-- ----------------------------------------------------------------------------
-- THE BETTER POSTURE, RECORDED RATHER THAN BUILT, WITH ITS HAZARD
-- ----------------------------------------------------------------------------
-- A SECURITY DEFINER function owned by the schema owner, doing pre-flight and
-- INSERT together, with EXECUTE granted to synapse_provisioner and nothing else,
-- is strictly better than this file. The role would hold one EXECUTE, the
-- pre-flight would become UNSKIPPABLE rather than merely called by the one
-- caller that exists today, and the two SELECTs above would belong to the
-- function's owner rather than to a login role.
--
-- IT IS NOT BUILT HERE because it is a new database object: a DDL file, a
-- migration, and its own approval. This file is a grant.
--
-- WHOEVER BUILDS IT MUST HANDLE search_path. A SECURITY DEFINER function without
-- an explicit `SET search_path` is a privilege-escalation surface: the caller
-- controls search_path, so an unqualified name inside the body can be resolved
-- to an object the CALLER created in a schema they can write, and it then
-- executes as the OWNER. The mitigation is both of:
--
--     CREATE FUNCTION synapse.enable_analysis(...) ...
--       SECURITY DEFINER
--       SET search_path = pg_catalog, synapse;
--
--   plus schema-qualifying every name in the body regardless. Note also that
--   REVOKE EXECUTE ... FROM PUBLIC is needed: EXECUTE is granted to PUBLIC by
--   default on a new function, which would hand the definer's rights to every
--   role in the database including synapse_writer.
--
-- ----------------------------------------------------------------------------
-- WHY THIS FILE IS NUMBERED AND provision_analysis.sql IS NOT
-- ----------------------------------------------------------------------------
-- Its header argues at length that numbering it `05_` would be wrong, and that
-- argument is correct and does not apply here. Provisioning happens PER TENANT,
-- for ever, and a fresh environment has no tenants: putting it in a bootstrap
-- checklist would eventually mean somebody provisions a tenant into an empty
-- database because the runbook said step 5.
--
-- A ROLE GRANT is the opposite. It runs ONCE PER ENVIRONMENT, in the same
-- dependency order as 01..04, and a fresh environment needs it before the
-- console can enable anything. It belongs in the numbered sequence, and the
-- README's run order gains a step.
--
-- ----------------------------------------------------------------------------
-- RUN AS: THE OWNER OF THE synapse SCHEMA
-- ----------------------------------------------------------------------------
--   STAGING : `postgres` (Synapse's Alembic runs as postgres, so it owns synapse)
--   LOCAL   : `ithina_dis_admin`
--
-- WHEN: after Synapse's Alembic has reached 0003 (which creates
-- synapse.provision), after DIS's Alembic has created canonical and
-- identity_mirror, and after the role exists. The role is created OUT OF BAND
-- like synapse_lifecycle, because a file in git that created a login role would
-- put a password in git:
--
--     CREATE ROLE synapse_provisioner WITH LOGIN NOSUPERUSER NOBYPASSRLS
--         NOCREATEDB NOCREATEROLE PASSWORD '<from Secret Manager>';
--     GRANT CONNECT ON DATABASE thalamus TO synapse_provisioner;
--
-- NOBYPASSRLS IS NOT DECORATION. synapse.provision is FORCE ROW LEVEL SECURITY
-- and its WITH CHECK pins every insert to the session's tenant GUC. A bypassing
-- role would let the console write a provision for a tenant it was not acting
-- for, and dis-rls's first-use guard refuses such a role anyway, so getting this
-- wrong fails at the first request rather than silently.
--
-- THE INVOCATION:
--
--   psql "host=127.0.0.1 dbname=thalamus user=postgres" \
--     -f 05_synapse_provisioner_grant.sql
--
-- Idempotent: GRANT and REVOKE are repeatable.
--
-- ----------------------------------------------------------------------------
-- THIS FILE REVOKES FROM ONE ROLE ONLY, AND THAT IS DELIBERATE
-- ----------------------------------------------------------------------------
-- sql/04 carries `REVOKE ALL ON ALL TABLES IN SCHEMA synapse FROM
-- synapse_reader`, which twice stripped privileges a later migration had
-- granted. The guard that caught it is
-- tests/test_grants_cover_reads.py::test_no_hand_run_file_revokes_what_a_migration_granted,
-- and it exists because a comment cannot compare two artifacts.
--
-- Every REVOKE below names synapse_provisioner and nothing else. This file
-- therefore cannot strip anything from any other role, whatever a future
-- migration grants. It is the narrowest re-assertable shape available and it is
-- the reason this is a new file rather than lines appended to sql/04.
-- ============================================================================


-- ---------- CONNECT, portable across the local and shared database names -----
SELECT 'GRANT CONNECT ON DATABASE ' || quote_ident(current_database())
       || ' TO synapse_provisioner'
\gexec


-- ---------- Narrow first ------------------------------------------------------
--
-- The only statements here that can REMOVE a privilege somebody added by hand.
-- Scoped to this role in all three schemas it touches, so re-running narrows it
-- back to exactly the posture below and the verification block proves it did.
REVOKE ALL ON ALL TABLES    IN SCHEMA synapse         FROM synapse_provisioner;
REVOKE ALL ON ALL TABLES    IN SCHEMA canonical       FROM synapse_provisioner;
REVOKE ALL ON ALL TABLES    IN SCHEMA identity_mirror FROM synapse_provisioner;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA synapse         FROM synapse_provisioner;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA canonical       FROM synapse_provisioner;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA identity_mirror FROM synapse_provisioner;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA synapse         FROM synapse_provisioner;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA canonical       FROM synapse_provisioner;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA identity_mirror FROM synapse_provisioner;


-- ---------- Schema usage ------------------------------------------------------
-- Three schemas, because the write is one transaction spanning three: the
-- pre-flight reads identity_mirror and canonical, the insert writes synapse.
GRANT USAGE ON SCHEMA synapse         TO synapse_provisioner;
GRANT USAGE ON SCHEMA canonical       TO synapse_provisioner;
GRANT USAGE ON SCHEMA identity_mirror TO synapse_provisioner;


-- ---------- The write: one table, one verb ------------------------------------
-- No UPDATE, so disabled_at cannot be set and a timezone cannot be edited. No
-- DELETE, so a provision cannot be removed. No SELECT, so the role cannot read
-- back what it wrote.
--
-- THIS COMMENT IS WHERE THE WRONG BELIEF WAS RECORDED, so the correction lives
-- here rather than only in the header. It used to read "ON CONFLICT DO NOTHING
-- needs none; RETURNING would, which is why the write does not use it". The
-- first half is FALSE: ON CONFLICT reads the arbiter index to detect the
-- conflict and that read needs SELECT, so the console's INSERT failed with
-- `permission denied for table provision` on every enable from the day 5e
-- deployed until 2026-08-10. The clause is gone and a duplicate is caught on
-- SQLSTATE 23505 plus the constraint name pk_provision instead. The claim about
-- RETURNING was always correct and still holds. The statement uses neither.
GRANT INSERT ON synapse.provision TO synapse_provisioner;


-- ---------- The pre-flight: exactly two SELECTs -------------------------------
-- identity_mirror.tenants is the FATAL check. It has no RLS, so a missing grant
-- here is LOUD (permission denied) rather than a silent zero.
GRANT SELECT ON identity_mirror.tenants TO synapse_provisioner;

-- canonical.store_sku_current_position is the WARN check. This one IS
-- FORCE ROW LEVEL SECURITY, so the three outcomes below look different and only
-- one of them is loud. The write path opens a TENANT-scoped session for the
-- tenant being enabled, which is what makes the count real:
--
--   missing GRANT   -> ERROR: permission denied for table ...   (LOUD)
--   GUCs not set    -> 0 rows, silently, and the endpoint would warn "no
--                      canonical positions" about a tenant with thousands
--   genuinely empty -> 0 rows, silently, and the warning is correct
GRANT SELECT ON canonical.store_sku_current_position TO synapse_provisioner;


-- ---------- Stated as SQL rather than as a comment, because a comment cannot
-- ---------- be re-run --------------------------------------------------------
--
-- THE DIRECTION IS THE SAFETY PROPERTY. Slice 5e builds enablement and
-- deliberately does not build disable or re-enable: synapse.provision holds ONE
-- window per (tenant, analysis), so clearing disabled_at loses the fact that
-- there was a gap and the attribution denominator for that period silently
-- becomes wrong. provision.sql names the append-only enablement history as the
-- fix and names its trigger: THE FIRST DISABLE.
--
-- Until that table exists, this REVOKE is what makes "the console cannot
-- re-enable" a property of the database rather than of the console's code. A
-- future slice that builds disable has to come here and argue with a line.
REVOKE UPDATE, DELETE, TRUNCATE ON synapse.provision FROM synapse_provisioner;

-- The role holds NOTHING on the log, the run table or the operator decision
-- table. It has never been granted anything there; these REVOKEs are what make
-- that a re-assertable fact rather than a historical accident. Same shape and
-- same reason as sql/04's canonical REVOKE for synapse_writer.
REVOKE ALL ON synapse.actions       FROM synapse_provisioner;
REVOKE ALL ON synapse.action_events FROM synapse_provisioner;
REVOKE ALL ON synapse.run           FROM synapse_provisioner;

-- And nothing on the second canonical table or the store mirror. The pre-flight
-- reads positions and tenant names; it has no business with sale events or with
-- identity_mirror.stores, whose per-STORE timezone is a different fact from the
-- per-TENANT reporting timezone this write records (see provision.sql).
REVOKE ALL ON canonical.store_sku_sale_events FROM synapse_provisioner;
REVOKE ALL ON identity_mirror.stores          FROM synapse_provisioner;

-- THE ORCHESTRATOR MUST NOT INHERIT THIS TABLE, restated here because migration
-- 0001 set ALTER DEFAULT PRIVILEGES granting synapse_writer INSERT on every
-- FUTURE table in the schema. That default did not touch synapse.provision
-- (0003 created it and revoked explicitly), and this line is the re-assertion:
-- if the orchestrator can enable a customer, a bug in the sweep can enable one.
REVOKE ALL ON synapse.provision FROM synapse_writer;

-- And the console's OTHER write identity must not acquire this one's job. Two
-- narrow roles are only narrower than one wide role while they stay distinct.
REVOKE ALL ON synapse.provision FROM synapse_lifecycle;


-- ============================================================================
-- VERIFY (run manually, as the schema owner. Each has a specific wrong answer)
-- ============================================================================
--
-- 1. EXACTLY the intended grants for this role, and no more. THREE rows.
--
--      SELECT table_schema, table_name, privilege_type
--        FROM information_schema.role_table_grants
--       WHERE grantee = 'synapse_provisioner'
--       ORDER BY 1, 2, 3;
--      -> canonical       | store_sku_current_position | SELECT
--         identity_mirror | tenants                    | SELECT
--         synapse         | provision                  | INSERT
--
--    A FOURTH ROW IS A FAULT, whatever it is. In particular:
--      - synapse | provision | SELECT   means the role can read enablement back,
--        and the console's three-state read is no longer forced through
--        synapse_reader.
--      - synapse | provision | UPDATE   means the console can disable a tenant
--        and re-enable one, which corrupts the attribution denominator silently.
--        That is the whole reason slice 5e ships enable and nothing else.
--
-- 2. The role holds NOTHING on the action log, the decision log or the run table.
--
--      SELECT count(*) FROM information_schema.role_table_grants
--       WHERE grantee = 'synapse_provisioner'
--         AND table_name IN ('actions', 'action_events', 'run');
--      -> 0
--
-- 3. NOTHING ELSE HOLDS INSERT ON synapse.provision. Enablement is one identity.
--
--      SELECT grantee, privilege_type FROM information_schema.role_table_grants
--       WHERE table_schema = 'synapse' AND table_name = 'provision'
--       ORDER BY 1, 2;
--      -> synapse_provisioner | INSERT
--         synapse_reader      | SELECT
--      Anything naming synapse_writer or synapse_lifecycle here is a fault: the
--      REVOKEs above should have removed it, so its presence means something
--      re-granted after this file last ran.
--
-- 4. The role cannot bypass RLS.
--
--      SELECT rolname, rolsuper, rolbypassrls FROM pg_roles
--       WHERE rolname = 'synapse_provisioner';
--      -> f, f
--
-- 5. RLS BITES ON INSERT, and this is the check that proves the write path needs
--    a TENANT-scoped session rather than the PLATFORM one every read here uses.
--    Connect AS synapse_provisioner.
--
--      BEGIN;
--      SELECT set_config('app.user_type','PLATFORM',true);
--      SELECT set_config('app.tenant_id','',true);
--      INSERT INTO synapse.provision (tenant_id, analysis_id, cadence, rung, timezone, enabled_at)
--      VALUES ('00000000-0000-0000-0000-0000000000aa', 'dead_stock', 'daily', 'shadow',
--              'Asia/Kolkata', now());
--      -- -> ERROR: new row violates row-level security policy for table "provision"
--      --    PLATFORM widens READS only. The tenant GUC is '' and NULLIF maps it to
--      --    NULL, so WITH CHECK matches no row. This is not a bug to work around.
--      ROLLBACK;
--
-- 6. AND IT BITES ACROSS TENANTS. Same role, TENANT scope, a row naming a
--    DIFFERENT tenant than the session.
--
--      BEGIN;
--      SELECT set_config('app.user_type','TENANT',true);
--      SELECT set_config('app.tenant_id','00000000-0000-0000-0000-0000000000aa',true);
--      INSERT INTO synapse.provision (tenant_id, analysis_id, cadence, rung, timezone, enabled_at)
--      VALUES ('00000000-0000-0000-0000-0000000000bb', 'dead_stock', 'daily', 'shadow',
--              'Asia/Kolkata', now());
--      -- -> ERROR: new row violates row-level security policy for table "provision"
--      ROLLBACK;
--
-- 7. THE PRE-FLIGHT READS ACTUALLY WORK, which is the pair this file exists to
--    satisfy and the one a grant check alone cannot prove. As synapse_provisioner,
--    against a tenant you know:
--
--      BEGIN;
--      SELECT set_config('app.user_type','TENANT',true);
--      SELECT set_config('app.tenant_id','<TENANT_UUID>',true);
--      SELECT name FROM identity_mirror.tenants WHERE tenant_id = '<TENANT_UUID>';
--      -- -> the name. A permission error means grant 1 above did not apply.
--      SELECT count(*) FROM canonical.store_sku_current_position
--       WHERE tenant_id = '<TENANT_UUID>';
--      -- -> the number of positions you know that tenant has. IF IT IS 0 AND YOU
--      --    EXPECTED ROWS, YOU HAVE MEASURED RLS, NOT THE GRANT. Re-check with
--      --    app.user_type='PLATFORM' before concluding the tenant is empty.
--      ROLLBACK;
--
-- 8. THE ROLE CANNOT UNDO ITS OWN WRITE, which is the direction property. As
--    synapse_provisioner, against a pair that exists:
--
--      UPDATE synapse.provision SET disabled_at = now();  -- permission denied
--      DELETE FROM synapse.provision;                     -- permission denied
--      SELECT count(*) FROM synapse.provision;            -- permission denied
--
--    All three are `permission denied`, not zero rows. A silent 0 on the last one
--    would mean the role holds SELECT and RLS hid the rows, which is verify 1's
--    fourth-row fault wearing a disguise.
-- ============================================================================
