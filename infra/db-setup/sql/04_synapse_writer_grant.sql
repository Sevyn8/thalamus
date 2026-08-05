-- ============================================================================
-- synapse_writer grants, and synapse_reader's grant on the action log.
--
-- ONE FILE, ONE WINDOW. Both roles' business with the synapse schema is here so
-- that provisioning the write path costs one database session, not two.
--
-- ----------------------------------------------------------------------------
-- MOSTLY REDUNDANT WITH THE MIGRATION, AND DELIBERATELY SO
-- ----------------------------------------------------------------------------
-- synapse/alembic/versions/0001_synapse_actions.py already issues these grants,
-- because a migration that creates a table and leaves it unreachable is a
-- migration that has not finished. This file exists for three reasons the
-- migration cannot serve:
--
--   1. RE-ASSERTION. Grants drift — someone widens one to debug something at
--      2am and does not narrow it. Re-running this narrows the roles back to
--      exactly what they should hold, and the verification block proves it did.
--   2. THE REVOKE. The migration grants; this file REVOKES first. That is the
--      only way to remove a privilege nobody remembers adding.
--   3. THE VERIFICATION BLOCK. The migration cannot check its own result from
--      the outside, and the checks at the end of this file are the ones that
--      distinguish "the grant ran" from "the posture is right".
--
-- RUN AS: the owner of the synapse schema — whoever ran Synapse's alembic.
--   LOCAL   : ithina_dis_admin
--   STAGING : postgres (cloudsqlsuperuser), which owns the other schemas there
-- WHEN: AFTER `alembic -c synapse/alembic.ini upgrade head`. The GRANTs name
-- synapse.actions, which does not exist until then.
--
-- ----------------------------------------------------------------------------
-- WHY A SECOND ROLE RATHER THAN WIDENING synapse_reader
-- ----------------------------------------------------------------------------
-- synapse_reader holds SELECT on canonical tables. Giving it INSERT anywhere
-- would mean the engine the RESOLVERS hold could write — and "resolvers never
-- write" is currently a code property, enforced by a grep test for INSERT/
-- UPDATE/DELETE imports.
--
-- Two roles make it a RUNTIME property. One process holds two engines: the
-- resolvers get the reader's, the action log gets the writer's. An INSERT added
-- to a resolver by mistake now fails at the database with a permission error
-- rather than at code review. And the converse matters as much: synapse_writer
-- has NO grant on canonical, so the log cannot read tenant data even by
-- accident.
--
-- ----------------------------------------------------------------------------
-- THE WRITER HAS NO SELECT, AND THAT IS NOT AN OVERSIGHT
-- ----------------------------------------------------------------------------
-- Appending needs INSERT and nothing else. `ON CONFLICT DO NOTHING` requires no
-- SELECT privilege, so idempotent appends work without one. `RETURNING` WOULD
-- require SELECT — which is why the log does not use it.
--
-- The consequence, stated because it shapes the tests: the writer cannot observe
-- whether its own append was suppressed. That is correct — `append()` returns
-- None by protocol — and it means anything verifying suppression must count rows
-- through synapse_reader, which is why the reader is granted SELECT here.
--
-- THAT GRANT WIDENS synapse_reader BEYOND ITS ORIGINAL TWO CANONICAL TABLES.
-- Deliberate: something will read the log back, and the alternative is every
-- read-side test holding an admin credential — a worse posture than a read-only
-- role reading a read-only thing. sql/03's verification block and the
-- resolvers' module docstring were updated in the same change, because both
-- said "exactly two tables" and both stopped being true here.
--
-- ----------------------------------------------------------------------------
-- APPEND-ONLY IS TWO MECHANISMS, AND THIS FILE IS ONLY ONE OF THEM
-- ----------------------------------------------------------------------------
-- The REVOKE below stops the APPLICATION from updating or deleting. It does
-- nothing about the table owner, who can do both. The other mechanism is the
-- BEFORE UPDATE OR DELETE trigger in the DDL, which raises for EVERY role
-- including the owner.
--
-- Neither covers: a superuser dropping the trigger, DROP TABLE, TRUNCATE by the
-- owner, or the fact that append-only says nothing about whether an appended row
-- was CORRECT. See the DDL header.
--
-- Idempotent: GRANT/REVOKE are repeatable.
-- ============================================================================


-- ---------- CONNECT, portable across the local and shared database names -----
SELECT 'GRANT CONNECT ON DATABASE ' || quote_ident(current_database())
       || ' TO synapse_writer'
\gexec


-- ---------- Schema usage -----------------------------------------------------
GRANT USAGE ON SCHEMA synapse TO synapse_writer;
GRANT USAGE ON SCHEMA synapse TO synapse_reader;


-- ---------- Narrow first, then grant exactly what each role needs ------------
--
-- REVOKE ALL first. This is the only statement in the file that can REMOVE a
-- privilege somebody added by hand, and it is the reason re-running this is
-- worth doing rather than assuming the migration's grants still hold.
REVOKE ALL ON ALL TABLES    IN SCHEMA synapse FROM synapse_writer;
REVOKE ALL ON ALL TABLES    IN SCHEMA synapse FROM synapse_reader;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA synapse FROM synapse_writer;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA synapse FROM synapse_reader;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA synapse FROM synapse_writer;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA synapse FROM synapse_reader;

-- INSERT ONLY for the writer. No UPDATE, no DELETE, no TRUNCATE, no SELECT.
GRANT INSERT ON synapse.actions TO synapse_writer;

-- SELECT for the reader, so the log can be read back without an admin credential.
GRANT SELECT ON synapse.actions TO synapse_reader;

-- Stated as SQL rather than as a comment, because a comment cannot be re-run.
REVOKE UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA synapse FROM synapse_writer;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA synapse FROM synapse_reader;

-- The writer must hold NOTHING on canonical. It has never been granted anything
-- there; this REVOKE is what makes that a re-assertable fact rather than a
-- historical accident.
REVOKE ALL ON ALL TABLES IN SCHEMA canonical FROM synapse_writer;
REVOKE USAGE ON SCHEMA canonical FROM synapse_writer;


-- ----------------------------------------------------------------------------
-- VERIFY (run manually — each has a specific wrong answer)
-- ----------------------------------------------------------------------------
--
-- 1. EXACTLY the intended grants, and no more. SEVEN rows since slice 6a; this
--    block said "Two rows" and named synapse_writer | UPDATE as a fault until
--    migration 0003 added synapse.provision and synapse.run.
--
--      SELECT grantee, table_name, privilege_type
--        FROM information_schema.role_table_grants
--       WHERE table_schema = 'synapse' AND grantee IN ('synapse_writer','synapse_reader')
--       ORDER BY 1, 2, 3;
--      -> synapse_reader | actions   | SELECT
--         synapse_reader | provision | SELECT
--         synapse_reader | run       | SELECT
--         synapse_writer | actions   | INSERT
--         synapse_writer | run       | INSERT
--         synapse_writer | run       | SELECT
--         synapse_writer | run       | UPDATE
--
--    THE WRITER NOW READS AND UPDATES, AND ONLY ON `run`. That table is a state
--    machine — claim a slot, discover whether the claim won, complete it — and a
--    write-only role cannot operate one. The property that mattered is intact and
--    is worth checking separately:
--
--      -- the writer must hold NOTHING on the action log except INSERT
--      SELECT privilege_type FROM information_schema.role_table_grants
--       WHERE grantee = 'synapse_writer' AND table_name = 'actions';
--      -> INSERT, and nothing else. A SELECT here would mean the append
--         credential can read the log back, which is the posture slice 5 built.
--
--      -- and nothing whatsoever on provision: enablement is an operator act
--      SELECT count(*) FROM information_schema.role_table_grants
--       WHERE grantee = 'synapse_writer' AND table_name = 'provision';
--      -> 0
--
--    NOTHING HOLDS INSERT ON synapse.provision, by design. Provisioning is done by
--    hand against the owner until a console exists, so a table no runtime role can
--    write cannot be widened by a bug.
--
-- 2. The writer holds NOTHING on canonical.
--
--      SELECT count(*) FROM information_schema.role_table_grants
--       WHERE grantee = 'synapse_writer' AND table_schema = 'canonical';
--      -> 0
--
-- 3. Neither role can bypass RLS.
--
--      SELECT rolname, rolsuper, rolbypassrls FROM pg_roles
--       WHERE rolname IN ('synapse_writer','synapse_reader');
--      -> both f, f
--
-- 4. RLS BITES ON INSERT for the writer — the check that proves the policy reads
--    the GENERATED tenant_id rather than a NULL. Connect AS synapse_writer.
--
--      BEGIN;
--      SELECT set_config('app.user_type','TENANT',true);
--      SELECT set_config('app.tenant_id','<A_TENANT_UUID>',true);
--      -- target naming a DIFFERENT tenant must be refused:
--      INSERT INTO synapse.actions (event_id, recorded_at, target, verb, quantity_at_stake,
--        expires_on, arm, declaration_id, declaration_version, capability_versions,
--        thresholds, as_of, payload_hash)
--      VALUES (gen_random_uuid(), now(),
--        '{"tenant_id":"aaaaaaaa-0000-0000-0000-00000000000a"}', 'review', NULL,
--        current_date, 'treatment', 'probe', '0.1.0', '{"x":"0.1.0"}', '{}', current_date, 'h');
--      -- -> ERROR: new row violates row-level security policy for table "actions"
--      ROLLBACK;
--
-- 5. THE APPEND-ONLY TRIGGER BITES FOR THE OWNER, which no grant can achieve.
--    Run as the schema owner, inside a transaction you will roll back.
--
--      BEGIN;
--      UPDATE synapse.actions SET verb = 'review';
--      -- -> ERROR: synapse.actions is append-only: UPDATE refused
--      DELETE FROM synapse.actions;
--      -- -> ERROR: synapse.actions is append-only: DELETE refused
--      ROLLBACK;
--
-- 6. The writer cannot UPDATE, DELETE or SELECT. As synapse_writer:
--
--      UPDATE synapse.actions SET verb = 'review';   -- permission denied
--      DELETE FROM synapse.actions;                  -- permission denied
--      SELECT count(*) FROM synapse.actions;         -- permission denied
--
-- 7. The reader CAN read it back, which is why it was granted. SET THE GUCs, AND
--    EXPECT A NUMBER YOU CAN CHECK. `>= 0, no error` was the expectation here
--    until 2026-08-04 and it is satisfied by a query that returns nothing because
--    RLS hid every row — the silent-zero this table's own header warns about.
--
--      -- as synapse_reader:
--      BEGIN;
--        SELECT set_config('app.user_type', 'TENANT', true);
--        SELECT set_config('app.tenant_id', '<TENANT_UUID>', true);
--        SELECT count(*) FROM synapse.actions;
--      ROLLBACK;
--      -> the number of actions you know that tenant has. If it is 0 and you
--         expected rows, you have measured RLS, not the grant. Re-check with
--         app.user_type='PLATFORM' before concluding the log is empty.
-- ============================================================================
