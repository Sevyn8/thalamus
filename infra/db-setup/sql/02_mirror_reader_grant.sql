-- ============================================================================
-- Thalamus shared DB: dis_mirror_reader cross-schema grant (POST-MIGRATION).
--
-- Adapted from DIS's create-dis-mirror-reader.sql. In the consolidated one-DB
-- world this is a same-database CROSS-SCHEMA read: dis_mirror_reader reads CM's
-- core.tenants / core.stores directly, no second instance and no second
-- connection. The grant statements are identical to the original; only the ROLE
-- CREATE is gone (Terraform's google_sql_user already created the role).
--
-- RUN AS: cloudsqlsuperuser (`postgres`), connected to the shared database.
--
-- WHEN: AFTER CM's Alembic has created core + core.tenants + core.stores.
-- Ordering dependency (hard): these GRANTs reference core.tenants / core.stores,
-- which do not exist until CM's migration runs. Running this before CM Alembic
-- fails with "relation core.tenants does not exist". See ../README.md step 5.
--
-- RLS posture unchanged: dis_mirror_reader is NOSUPERUSER NOBYPASSRLS, so reads
-- must run in a transaction with app.user_type='PLATFORM' and app.tenant_id=NULL
-- (CM's D-29 PLATFORM OR-branch), exactly as in the cross-instance version.
--
-- Idempotent: GRANT/REVOKE are repeatable.
-- ============================================================================

-- USAGE on CM's schema, SELECT on the two tables DIS mirrors.
GRANT USAGE ON SCHEMA core TO dis_mirror_reader;

GRANT SELECT ON core.tenants TO dis_mirror_reader;
GRANT SELECT ON core.stores  TO dis_mirror_reader;

-- Defensive: strip anything broader, then re-affirm exactly the two SELECTs.
REVOKE ALL ON ALL TABLES    IN SCHEMA core FROM dis_mirror_reader;
GRANT  SELECT ON core.tenants TO dis_mirror_reader;
GRANT  SELECT ON core.stores  TO dis_mirror_reader;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA core FROM dis_mirror_reader;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA core FROM dis_mirror_reader;

-- Verify (run manually):
--   SELECT grantee, table_schema, table_name, privilege_type
--     FROM information_schema.role_table_grants
--     WHERE grantee = 'dis_mirror_reader';
--   -> exactly two rows: SELECT on core.tenants and core.stores.
