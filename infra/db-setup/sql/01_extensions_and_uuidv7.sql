-- ============================================================================
-- Thalamus shared DB: privileged one-time setup (extensions + canonical uuidv7).
--
-- RUN AS: the cloudsqlsuperuser (`postgres`) role, connected to the shared
-- database (var.database_name, default "thalamus"). The application roles
-- (user_admin_backend, ithina_dis_user, dis_mirror_reader) are NOSUPERUSER and
-- CANNOT run CREATE EXTENSION, so this step must run as postgres.
--
-- WHEN: once, immediately after `terraform apply` creates the instance +
-- database + roles, and BEFORE either app's Alembic runs. See ../README.md for
-- the full ordering.
--
-- Idempotent: IF NOT EXISTS on extensions; CREATE OR REPLACE on the function.
-- ============================================================================


-- ----------------------------------------------------------------------------
-- 1. Extensions (created here so each app's Alembic finds them already present)
-- ----------------------------------------------------------------------------
-- vector    : pgvector (Thalamus target; not enabled by either app today).
-- ltree     : CM org_nodes materialised-path queries.
-- pgcrypto  : gen_random_uuid() backstop / general crypto (both apps reference).
-- btree_gist: DIS EXCLUDE constraints (DIS Alembic 0005 does
--             `CREATE EXTENSION IF NOT EXISTS btree_gist`; creating it here as
--             superuser first makes that a no-op, since ithina_dis_user cannot
--             create it on Cloud SQL).
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS ltree;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS btree_gist;


-- ----------------------------------------------------------------------------
-- 2. Canonical uuidv7() in public
-- ----------------------------------------------------------------------------
-- Both CM and DIS ship a uuidv7() with a BYTE-FOR-BYTE IDENTICAL body (both
-- vendored from kjmph's PL/pgSQL reference, RFC 9562). They differ only in
-- placement. We install ONE canonical copy in `public` so every role resolves
-- `uuidv7()` unqualified via public on its search_path (CM uses core,public;
-- DIS uses its schemas + public).
--
-- Canonical choice: DIS's public.uuidv7() placement (schema-qualified to
-- public), because in a SHARED database `public` is the only schema on every
-- role's search_path. CM's version is unqualified and would land in `core`
-- (invisible to DIS unqualified). The function body is the same either way.
--
-- --- CM definition (cm-backend/db/raw_ddl/Ithina_postgres_SQL_DDL_shared_utilities_v1.sql) ---
--   create or replace function uuidv7()
--   returns uuid
--   as $$
--   begin
--     return encode(
--       set_bit(
--         set_bit(
--           overlay(uuid_send(gen_random_uuid())
--                   placing substring(int8send(floor(extract(epoch from clock_timestamp()) * 1000)::bigint) from 3)
--                   from 1 for 6
--           ),
--           52, 1
--         ),
--         53, 1
--       ),
--       'hex')::uuid;
--   end
--   $$ language plpgsql volatile;
--
-- --- DIS definition (ithina-retail-dis/schemas/postgres/00_extensions/uuidv7_setup.sql) ---
--   CREATE OR REPLACE FUNCTION public.uuidv7() RETURNS uuid
--       LANGUAGE plpgsql
--       AS $$
--       begin
--           return encode(
--               set_bit(
--                   set_bit(
--                       overlay(uuid_send(gen_random_uuid())
--                               placing substring(int8send(floor(extract(epoch from clock_timestamp()) * 1000)::bigint) from 3)
--                               from 1 for 6
--                       ),
--                       52, 1
--                   ),
--                   53, 1
--               ),
--               'hex')::uuid;
--       end
--       $$;
--
-- The two bodies are identical. We use DIS's public-qualified form verbatim.
-- ----------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION public.uuidv7() RETURNS uuid
    LANGUAGE plpgsql
    AS $$
begin
    -- use random v4 uuid as starting point (which has the same variant we need)
    -- then overlay timestamp
    -- then set version 7 by flipping the 2 and 1 bit in the version 4 string
    return encode(
        set_bit(
            set_bit(
                overlay(uuid_send(gen_random_uuid())
                        placing substring(int8send(floor(extract(epoch from clock_timestamp()) * 1000)::bigint) from 3)
                        from 1 for 6
                ),
                52, 1
            ),
            53, 1
        ),
        'hex')::uuid;
end
$$;

COMMENT ON FUNCTION public.uuidv7() IS
'UUIDv7 generator (RFC 9562). Vendored from kjmph PL/pgSQL reference. Canonical Thalamus copy in public, shared by CM (core schema) and DIS (its schemas). Identical body to both apps original definitions.';

-- Both apps EXECUTE this; functions are EXECUTE-to-PUBLIC by default. Explicit
-- for clarity.
GRANT EXECUTE ON FUNCTION public.uuidv7() TO PUBLIC;
