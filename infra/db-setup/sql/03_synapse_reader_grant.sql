-- ============================================================================
-- synapse_reader canonical grant (POST-MIGRATION).
--
-- Synapse is a PEER of DIS, not part of it. It reads canonical READ-ONLY and never
-- writes a DIS table. This file gives its role exactly the two CANONICAL tables its
-- resolvers name, and nothing else.
--
-- SINCE SLICE 5 the role also holds SELECT on synapse.actions — Synapse's OWN
-- schema, granted by sql/04, so the action log can be read back without an admin
-- credential. Still read-only everywhere: appending is synapse_writer's job, a
-- separate role holding INSERT and nothing else.
--
-- Modelled on 02_mirror_reader_grant.sql deliberately: dis_mirror_reader is the
-- precedent for "a consumer reads a schema it does not own", it works, and a
-- second pattern would be a second thing to keep correct. Only the ROLE CREATE is
-- absent here too — Terraform's google_sql_user already made the role in cloud,
-- and dis/infra/local/postgres-init.sql makes it on a fresh local volume.
--
-- ----------------------------------------------------------------------------
-- RUN AS: THE OWNER OF `canonical` — WHICH DIFFERS BY ENVIRONMENT
-- ----------------------------------------------------------------------------
--   STAGING : `postgres`. DIS's Alembic was run as postgres against the shared
--             `thalamus` database (../README.md status note, 2026-07-20), so
--             cloudsqlsuperuser owns canonical there.
--   LOCAL   : `ithina_dis_admin`. docker-compose's POSTGRES_USER runs the local
--             Alembic, so it owns canonical on 5433/ithina_dis_db.
--
-- Getting this wrong fails loudly with 'permission denied for schema canonical'.
-- It is the mirror image of sql/02's note, where `postgres` is the WRONG role
-- because user_admin_backend owns `core`.
--
-- ----------------------------------------------------------------------------
-- WHEN: AFTER DIS's Alembic
-- ----------------------------------------------------------------------------
-- Hard ordering dependency: these GRANTs name canonical.store_sku_current_position
-- and canonical.store_sku_sale_events, which do not exist until DIS migrates.
-- Running early fails with "relation ... does not exist". Same shape as sql/02's
-- dependency on CM's Alembic. See ../README.md.
--
-- ----------------------------------------------------------------------------
-- THE DSN SECRET IS CREATED BY HAND, OUTSIDE TERRAFORM
-- ----------------------------------------------------------------------------
-- This surprises people, so the whole runbook is here rather than split across
-- two places. Terraform owns the role and its PASSWORD secret; it only ever READS
-- the DSN secrets (`data "google_secret_manager_secret"`). There is no resource
-- creating any *-database-url anywhere in infra/ — staging/main.tf calls them
-- "the out-of-band Secret Manager secrets" and means it.
--
-- So, after `terraform apply` and after this file has run:
--
--   1. Read the generated password (Terraform made the container + version):
--        gcloud secrets versions access latest \
--          --secret=thalamus-synapse_reader-password --project=<PROJECT>
--
--   2. Create the DSN secret BY HAND, exactly as dis-mirror-reader-database-url
--      was created. Note the naming asymmetry, which is the existing convention
--      and is preserved rather than tidied: password secrets carry the role name
--      verbatim (underscore), DSN secrets are hyphenated.
--        gcloud secrets create synapse-reader-database-url --project=<PROJECT> \
--          --replication-policy=automatic
--        printf 'postgresql+psycopg://synapse_reader:<PASSWORD>@<PRIVATE_IP>:5432/thalamus' \
--          | gcloud secrets versions add synapse-reader-database-url \
--              --project=<PROJECT> --data-file=-
--
--      DRIVER: `postgresql+psycopg` (psycopg3), which is what every DSN in this
--      project uses — POSTGRES_URL, POSTGRES_ADMIN_URL, alembic.ini. NOT asyncpg:
--      it is not a workspace dependency, and `postgresql+asyncpg://` fails at
--      connect with ModuleNotFoundError. psycopg3 serves both the sync and async
--      engines, so one scheme covers dis-rls's create_async_engine and psql-side
--      tooling alike.
--
--      The password's override_special is reserved to "_-." precisely so it embeds
--      in this URL without percent-encoding.
--
--      LOCAL equivalent, for SYNAPSE_READER_URL against the devbox (the password is
--      the fixed literal in dis/infra/local/postgres-init.sql):
--        postgresql+psycopg://synapse_reader:synapse_reader_password@localhost:5433/ithina_dis_db
--
--   3. NOTHING BINDS THIS SECRET. No Cloud Run service or job mounts it and no
--      service account holds secretAccessor on it. That is deliberate: nothing
--      runs as synapse_reader in production yet. It exists so Synapse's
--      integration tests run as the identity the resolvers are designed for,
--      instead of borrowing ithina_dis_user's full DML on canonical.
--
-- ----------------------------------------------------------------------------
-- WHY EXACTLY TWO CANONICAL TABLES
-- ----------------------------------------------------------------------------
-- These are every canonical table Synapse names, verified by grep over
-- synapse/src/synapse/resolvers/ and pinned by a test
-- (tests/unit/test_table_name_containment.py) that fails if a table name appears
-- anywhere outside that package:
--
--   canonical.store_sku_current_position  <- resolvers/current_state.py
--   canonical.store_sku_sale_events       <- resolvers/daily_series.py
--
-- resolvers/_collapse.py names NO table (it is parameterised). Nothing touches
-- identity_mirror, config, bronze, audit, staging, quarantine or telemetry.
-- Foreign keys need no SELECT on their targets.
--
-- One query is made that is NOT covered here and needs no grant: dis-rls reads
-- pg_roles on first use of every engine to verify rolsuper/rolbypassrls. pg_roles
-- is SELECT-to-PUBLIC in stock Postgres.
--
-- ----------------------------------------------------------------------------
-- RLS POSTURE, AND THE FAILURE MODE THAT LOOKS LIKE SUCCESS
-- ----------------------------------------------------------------------------
-- synapse_reader is NOSUPERUSER NOBYPASSRLS. Both canonical tables are ENABLE +
-- FORCE ROW LEVEL SECURITY with a single policy:
--
--   USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
--          OR current_setting('app.user_type', true) = 'PLATFORM')
--
-- With the GUCs unset, current_setting(..., true) returns NULL, the comparison is
-- NULL rather than true, and the policy excludes every row. THE RESULT IS ZERO
-- ROWS, NO ERROR, NO WARNING. FORCE means this holds even for an owner.
--
-- So three different situations produce results an operator cannot tell apart at
-- a glance, and only one of them is loud:
--
--   missing GRANT        -> ERROR: permission denied for table ...   (LOUD)
--   GUCs not set         -> 0 rows, silently
--   tenant has no data   -> 0 rows, silently
--
-- dis-rls's rls_session always sets both GUCs, so the middle case only arises from
-- a query written outside it — which is why Synapse's resolvers have no such path.
-- The verification block below is how you confirm which case you are in, rather
-- than inferring it. Run it; do not assume it.
--
-- Idempotent: GRANT/REVOKE are repeatable.
-- ============================================================================


-- CONNECT on whichever database this is run against. Written portably (the
-- 00_bootstrap/roles.sql form) so ONE file serves the local `ithina_dis_db` and the
-- shared `thalamus` database without an edit.
SELECT 'GRANT CONNECT ON DATABASE ' || quote_ident(current_database())
       || ' TO synapse_reader'
\gexec

-- USAGE on the schema, SELECT on the two tables the resolvers name.
GRANT USAGE ON SCHEMA canonical TO synapse_reader;

GRANT SELECT ON canonical.store_sku_current_position TO synapse_reader;
GRANT SELECT ON canonical.store_sku_sale_events      TO synapse_reader;

-- Defensive: strip anything broader, then re-affirm exactly the two SELECTs.
--
-- THIS MATTERS MORE HERE THAN IT DID IN sql/02. Migration 0001 set ALTER DEFAULT
-- PRIVILEGES on every DIS schema granting SELECT/INSERT/UPDATE/DELETE to
-- ithina_dis_user. Those defaults are per-grantor and do not name synapse_reader,
-- so they cannot leak to it today — but a future default-privileges change, or a
-- careless GRANT ... ON ALL TABLES, would silently widen this role. Re-running this
-- file narrows it back to two tables, and the verification block proves it did.
REVOKE ALL ON ALL TABLES    IN SCHEMA canonical FROM synapse_reader;
GRANT  SELECT ON canonical.store_sku_current_position TO synapse_reader;
GRANT  SELECT ON canonical.store_sku_sale_events      TO synapse_reader;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA canonical FROM synapse_reader;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA canonical FROM synapse_reader;

-- No write, anywhere, ever. Stated as SQL rather than as a comment, because a
-- comment cannot be re-run.
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA canonical FROM synapse_reader;


-- ============================================================================
-- identity_mirror: the tenant and store names the CONSOLE reads (slice 8a)
-- ============================================================================
-- WHY THIS ROLE AND NOT AN HTTP CALL. synapse-ui-server's /fleet, /tenants/{id}
-- and /runs all join identity_mirror for a name. The alternative considered was
-- the BFF asking cm-backend over HTTP, which is a cleaner boundary and was
-- rejected on CORRECTNESS, not taste: /fleet's guarantee that EVERY MIRRORED
-- TENANT APPEARS is a LEFT JOIN from identity_mirror.tenants with the LIMIT
-- pushed down. Over HTTP that becomes fetch-all-then-join-in-Python — the
-- guarantee moves out of the database into application logic and the bound is
-- lost. It also puts cm-backend in the read path's availability, for a name.
--
-- THIS CROSSES NO BOUNDARY THAT IS NOT ALREADY CROSSED. identity_mirror is DIS's
-- schema — and so is canonical, which this role has read since it existed.
--
-- THE PRECEDENT IS sql/02: dis_mirror_reader gets USAGE on core plus SELECT on
-- core.tenants and core.stores. Identical shape, the same two tables one hop
-- upstream. This is the established pattern here, not a new one.
--
-- BOTH TABLES, NOT JUST tenants. stores is counted in _FLEET and in _TENANT;
-- granting only tenants moves the failure rather than fixing it.
--
-- NO RLS TO SATISFY, VERIFIED FOUR WAYS rather than assumed, because this
-- project has lost six incidents to the FORCE RLS silent zero: neither table has
-- ENABLE ROW LEVEL SECURITY, nor FORCE, nor any CREATE POLICY, and both DDL
-- files state "RLS not enabled" in their table comments. So a missing grant here
-- fails LOUDLY with 42501 rather than returning zero rows — and the grant alone
-- is sufficient. (The FORCE RLS tables this role reads — canonical.* and
-- synapse.* — are a different matter and are already correct: each policy's
-- USING clause carries the `app.user_type = 'PLATFORM'` disjunct, and the BFF
-- opens every session through rls_platform_session.)
GRANT USAGE ON SCHEMA identity_mirror TO synapse_reader;

GRANT SELECT ON identity_mirror.tenants TO synapse_reader;
GRANT SELECT ON identity_mirror.stores  TO synapse_reader;

-- Same defensive narrowing as canonical above: strip anything broader, then
-- re-affirm exactly the two SELECTs.
REVOKE ALL ON ALL TABLES    IN SCHEMA identity_mirror FROM synapse_reader;
GRANT  SELECT ON identity_mirror.tenants TO synapse_reader;
GRANT  SELECT ON identity_mirror.stores  TO synapse_reader;

REVOKE ALL ON ALL SEQUENCES IN SCHEMA identity_mirror FROM synapse_reader;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA identity_mirror FROM synapse_reader;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON ALL TABLES IN SCHEMA identity_mirror FROM synapse_reader;


-- ----------------------------------------------------------------------------
-- VERIFY (run manually — each of these has a specific wrong answer)
-- ----------------------------------------------------------------------------
--
-- 1. EXACTLY these grants, all SELECT. A privilege_type other than SELECT means a
--    write path exists; an extra table means the REVOKE above missed something.
--
--      SELECT table_schema, table_name, privilege_type
--        FROM information_schema.role_table_grants
--       WHERE grantee = 'synapse_reader'
--       ORDER BY 1, 2;
--      -> canonical | store_sku_current_position | SELECT
--         canonical | store_sku_sale_events      | SELECT
--         synapse   | actions                    | SELECT
--         synapse   | provision                  | SELECT
--         synapse   | run                        | SELECT
--
--    THE THIRD ROW ARRIVED IN SLICE 5 and this block said "exactly two" until then.
--    synapse_reader was granted SELECT on the action log because something will read
--    it back, and the alternative was every read-side test holding an admin
--    credential — a worse posture than a read-only role reading a read-only thing.
--    THE LAST TWO ARRIVED IN SLICE 6a with migration 0003: the orchestrator
--    enumerates synapse.provision under PLATFORM scope, and synapse.run is read
--    back to show what ran. All three synapse grants are issued by the migrations
--    and sql/04, not here; this list is the whole picture.
--
-- 2. The role cannot bypass RLS. Both columns must be `f`. If either is `t`,
--    tenant isolation is void for this role and dis-rls will refuse the engine on
--    its first query (RlsContextError) — which is the loud backstop, not a reason
--    to skip this check.
--
--      SELECT rolname, rolsuper, rolbypassrls, rolcanlogin
--        FROM pg_roles WHERE rolname = 'synapse_reader';
--      -> rolsuper = f, rolbypassrls = f, rolcanlogin = t
--
-- 3. RLS ACTUALLY BITES for this role. Connect AS synapse_reader (not as the owner)
--    and read with no GUCs set. This is the check-setup.sh:294 pattern, and it is
--    the only one that distinguishes "denied" from "empty".
--
--      -- psql "host=... dbname=... user=synapse_reader"
--      SELECT set_config('app.tenant_id', NULL, FALSE);
--      SELECT set_config('app.user_type', NULL, FALSE);
--      SELECT COUNT(*) FROM canonical.store_sku_sale_events;
--      -> 0     : correct. RLS is enforced.
--      -> >0    : RLS IS BYPASSED. Stop and investigate before anything reads.
--      -> ERROR : the GRANT above did not apply.
--
-- 4. And that it reads real rows WITH the GUCs set, so check 3 was not passing
--    because the table is empty. Substitute a tenant that has data.
--
--      BEGIN;
--      SELECT set_config('app.user_type', 'TENANT', TRUE);
--      SELECT set_config('app.tenant_id', '<TENANT_UUID>', TRUE);
--      SELECT COUNT(*) FROM canonical.store_sku_sale_events;
--      ROLLBACK;
--      -> >0 on a tenant with ingested sales. If this is also 0, check 3 proved
--         nothing — the table is empty and you have not tested RLS at all.
--
-- 5. Writes are refused. The REVOKE is only meaningful if someone has watched it
--    fire.
--
--      -- as synapse_reader, inside a transaction you will roll back:
--      BEGIN;
--      DELETE FROM canonical.store_sku_sale_events;
--      -- -> ERROR: permission denied for table store_sku_sale_events
--      ROLLBACK;
-- ============================================================================
