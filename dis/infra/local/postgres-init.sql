-- Runs once on first container start (fresh volume).
-- Creates the application role with production-correct posture:
--   NOSUPERUSER  → role is NOT a superuser
--   NOBYPASSRLS  → RLS policies apply to this role; queries that lack
--                  app.tenant_id context will return empty results, not
--                  silently leak cross-tenant data.
--
-- The bootstrap superuser is ithina_dis_admin (from docker-compose
-- POSTGRES_USER); used only for migrations.

CREATE ROLE ithina_dis_user
  WITH LOGIN
       NOSUPERUSER
       NOBYPASSRLS
       NOCREATEDB
       NOCREATEROLE
       PASSWORD 'ithina_dis_password';

-- Grant connect on the database
GRANT CONNECT ON DATABASE ithina_dis_db TO ithina_dis_user;

-- Grant usage on the default public schema (DIS schemas come from
-- Alembic migrations and will need their own GRANT statements).
GRANT USAGE ON SCHEMA public TO ithina_dis_user;


-- ---------------------------------------------------------------------------
-- synapse_reader — Synapse's read-only role (local devbox equivalent of the
-- Terraform google_sql_user in infra/modules/cloud-sql).
--
-- Same posture as ithina_dis_user and for the same reason: NOSUPERUSER
-- NOBYPASSRLS, so canonical's FORCE RLS policies apply. A read-only analytics
-- plane must be subject to RLS like every other consumer, and dis-rls refuses
-- any engine whose role reports rolsuper or rolbypassrls.
--
-- ONLY THE ROLE IS HERE. The GRANTs are not, and cannot be: this file runs at
-- container init, long before Alembic creates `canonical`. They live in
-- infra/db-setup/sql/03_synapse_reader_grant.sql, run by hand after
-- `make db-migrate` (as ithina_dis_admin locally — it owns canonical here).
-- Without that step this role can log in and read nothing.
--
-- THIS FILE ONLY RUNS ON A FRESH VOLUME (docker-entrypoint-initdb.d). An existing
-- devbox will NOT have this role after a git pull. Either `make reset-local`
-- (wipes the volume), or run this one line by hand against 5433 as
-- ithina_dis_admin:
--
--   CREATE ROLE synapse_reader WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD 'synapse_reader_password';
--
-- The password is a fixed devbox literal, exactly like ithina_dis_password above.
-- No env var: this file has no precedent for one, and the role reaches nothing
-- but a local container.
-- ---------------------------------------------------------------------------

CREATE ROLE synapse_reader
  WITH LOGIN
       NOSUPERUSER
       NOBYPASSRLS
       NOCREATEDB
       NOCREATEROLE
       PASSWORD 'synapse_reader_password';

GRANT CONNECT ON DATABASE ithina_dis_db TO synapse_reader;


-- ---------------------------------------------------------------------------
-- synapse_writer — Synapse's WRITE role, and a SECOND role rather than a
-- widened synapse_reader.
--
-- INSERT on synapse.actions and nothing else: no UPDATE, no DELETE, no
-- TRUNCATE, and deliberately no SELECT (ON CONFLICT DO NOTHING needs none;
-- RETURNING would, so the log does not use it). Nothing on canonical.
--
-- WHY TWO ROLES. "Resolvers never write" is otherwise only a code property,
-- enforced by a grep test. With two roles one process holds two engines — the
-- resolvers get the reader's, the action log gets the writer's — so an INSERT
-- added to a resolver by mistake fails at the DATABASE rather than at review.
--
-- NOSUPERUSER NOBYPASSRLS like every other role here: synapse.actions is a
-- multi-tenant table with two-GUC RLS, and the writer inserts inside an
-- rls_session so the policy's WITH CHECK pins the row to the session's tenant.
--
-- THE GRANTS ARE NOT HERE. They name synapse.actions, which does not exist
-- until Synapse's own alembic chain has run:
--     SYNAPSE_ADMIN_URL=... uv run alembic -c synapse/alembic.ini upgrade head
-- then infra/db-setup/sql/04_synapse_writer_grant.sql. Without those this role
-- can log in and reach nothing.
--
-- THE WRITE TESTS DO NOT NEED ANY OF THAT DONE TO *THIS* DATABASE. Synapse's
-- live write tests refuse to run against a real database at all: they build a
-- DISPOSABLE clone of this one and run the chain against the clone. See
-- synapse/tests/integration/conftest.py. The role, though, is cluster-wide and
-- so is still wanted here — the harness creates it if it is missing, which it
-- is on any devbox whose volume predates this block.
--
-- FRESH VOLUME ONLY, same as the role above. On an existing devbox either
-- `make reset-local`, or run this one line by hand against 5433 as
-- ithina_dis_admin:
--
--   CREATE ROLE synapse_writer WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD 'synapse_writer_password';
--
-- Fixed devbox literal, exactly like the two roles above.
-- ---------------------------------------------------------------------------

CREATE ROLE synapse_writer
  WITH LOGIN
       NOSUPERUSER
       NOBYPASSRLS
       NOCREATEDB
       NOCREATEROLE
       PASSWORD 'synapse_writer_password';

GRANT CONNECT ON DATABASE ithina_dis_db TO synapse_writer;

-- ---------------------------------------------------------------------------
-- synapse_lifecycle — the CONSOLE's write identity (slice 5d)
-- ---------------------------------------------------------------------------
-- A THIRD role rather than reusing synapse_writer, and the reason is attribution:
-- synapse_writer is the orchestrator's identity (INSERT on synapse.actions, no
-- SELECT anywhere). Lending it to an HTTP surface would make every row ambiguous
-- about which process caused it and would hand the console a credential that can
-- append to the action log.
--
-- It holds INSERT on synapse.action_events and NOTHING ELSE. The console reads
-- that table through synapse_reader. So what an operator's click can do is bounded
-- by the grant, not by which code path was taken.
--
-- NOBYPASSRLS matters here specifically: synapse.action_events is FORCE ROW LEVEL
-- SECURITY and its WITH CHECK pins each insert to the session's tenant, so a
-- bypassing role could write an event against a tenant it was not acting for.
--
-- THE GRANTS ARE NOT HERE. They name synapse.action_events, which does not exist
-- until migration 0006 has run:
--     SYNAPSE_ADMIN_URL=... uv run alembic -c synapse/alembic.ini upgrade head
-- Without that this role can log in and reach nothing.
--
-- FRESH VOLUME ONLY, same as the two above. On an existing devbox run this one
-- line by hand against 5433 as ithina_dis_admin:
--
--   CREATE ROLE synapse_lifecycle WITH LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE PASSWORD 'synapse_lifecycle_password';
CREATE ROLE synapse_lifecycle
       WITH LOGIN
       NOSUPERUSER
       NOBYPASSRLS
       NOCREATEDB
       NOCREATEROLE
       PASSWORD 'synapse_lifecycle_password';

GRANT CONNECT ON DATABASE ithina_dis_db TO synapse_lifecycle;
