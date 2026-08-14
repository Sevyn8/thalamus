-- ============================================================================
-- user_admin_backend on axon.channel_connections: Customer Master's one reach
-- into the Axon schema (Axon slice 5).
--
-- THE FIRST FILE IN THIS SERIES THAT GRANTS AN EXISTING ROLE RATHER THAN A NEW
-- ONE, and that is the whole reason this design is cheap. sql/05 through 08 each
-- brought a new login role, which means a CREATE ROLE out of band, a password in
-- Secret Manager, a DSN, and a service configured to use it. This file brings
-- none of that: user_admin_backend is cm-backend's existing application role, it
-- already connects to this database, and CM already opens exactly the session
-- posture this table's policy needs.
--
-- ----------------------------------------------------------------------------
-- WHY CUSTOMER MASTER WRITES A TABLE IN THE AXON SCHEMA AT ALL
-- ----------------------------------------------------------------------------
-- The tenant administrator types their own provider credential into CM, because
-- CM is where tenant configuration and the permission model live. The row that
-- results belongs to Axon's plane. Both live in the SAME DATABASE: this Cloud SQL
-- instance carries exactly one application database and its Terraform module says
-- so in as many words ("The single shared database ... BOTH apps must point their
-- DATABASE_URL at this one db. CM's core schema and DIS's 8 schemas coexist
-- here.").
--
-- The alternative was an HTTP endpoint on an Axon service. There is no Axon HTTP
-- surface: axon-sender is a poll loop whose module carries two tests forbidding an
-- invoker binding, and synapse-ui-server gates every route on require_platform
-- while this caller is a TENANT admin. A grant is the smaller thing.
--
-- ----------------------------------------------------------------------------
-- SELECT, INSERT, UPDATE. NO DELETE. AND THE SELECT IS LOAD-BEARING TWICE.
-- ----------------------------------------------------------------------------
-- SELECT serves two reads and one write:
--
--   the tenant's own view      GET /api/v1/channels, under a TENANT session, so
--                              the policy's equality branch scopes it.
--   the operator's fleet view  GET /api/v1/channels/platform, under a PLATFORM
--                              session, so the policy's USING branch widens it.
--   THE UPSERT'S ARBITER READ  and this is the one that is easy to miss.
--
-- ON CONFLICT READS THE ARBITER INDEX, WHICH IS A SELECT PRIVILEGE ON THE TABLE.
-- Slice 5e spent two days with every enable in production failing with
-- `permission denied for table provision` behind a green apply, because the
-- writing role held INSERT and no SELECT. axon.channel_connections' own DDL
-- carries that warning, naming 5e and 06_axon_sender_grant.sql, directly above
-- the primary key the upsert arbitrates on.
--
-- The difference here is the ROLE, not the mechanism. axon_sender deliberately
-- holds no SELECT anywhere and still does. user_admin_backend needs SELECT for
-- the two reads regardless, so the arbiter read costs nothing extra, and the
-- grant lands in the same commit as the statement that depends on it. Do not
-- read this as "ON CONFLICT is fine now"; read it as "this role holds the SELECT
-- that ON CONFLICT needs, and that was checked".
--
-- NO DELETE, and the absence is a decision. A tenant disconnecting a channel is a
-- status flip, not a vanished row: the row carries the NAME of a Secret Manager
-- secret, and a deleted row leaves that secret live with nothing pointing at it
-- and nothing able to attribute it. Deletion would manufacture exactly the orphan
-- the deterministic name exists to prevent.
--
-- NOTHING ON axon.channel_templates. The registry ships empty and stays empty
-- until an adapter can verify a send; a grant on it now would be a credential
-- reaching a table no code opens a session against. Same rule as slice 1's, and
-- the reason both tables were ungranted when they were created.
--
-- ----------------------------------------------------------------------------
-- THE SESSION POSTURE IS HALF THE MECHANISM AND IT IS NOT IN THIS FILE
-- ----------------------------------------------------------------------------
-- axon.channel_connections is FORCE ROW LEVEL SECURITY with the PLATFORM branch
-- in USING only. This grant lets user_admin_backend reach the table; the POLICY
-- decides which rows, and it decides that from app.tenant_id and app.user_type.
--
-- CM sets both, per request, in get_tenant_session_dep, from the verified token
-- and nothing else. That is what makes a TENANT write land on the caller's own
-- tenant (WITH CHECK pins it) and a PLATFORM read cross every tenant (USING
-- widens it).
--
-- WITH THE GUCs UNSET, A SELECT HERE RETURNS ZERO ROWS AND RAISES NOTHING. That
-- is indistinguishable from "no tenant has configured a channel", and it has
-- bitten this estate seven times in three days, once on a DELETE as the table
-- owner. The verification block at the foot of this file therefore states its
-- posture explicitly rather than relying on whatever the psql session happens to
-- carry.
--
-- ----------------------------------------------------------------------------
-- RUN AS: THE OWNER OF THE axon SCHEMA
-- ----------------------------------------------------------------------------
--   STAGING : `postgres` (Axon's Alembic runs as postgres, so it owns axon)
--   LOCAL   : whoever created the schema
--
-- WHEN: after Axon's Alembic has reached 0002 (which creates the table), and
-- before cm-backend's first channels write. NO CREATE ROLE PREREQUISITE: the role
-- already exists and already has a password and a DSN.
--
--   psql "host=127.0.0.1 dbname=thalamus user=postgres" \
--     -f 09_cm_channel_connections_grant.sql
--
-- Idempotent: GRANT and REVOKE are repeatable.
--
-- ----------------------------------------------------------------------------
-- THIS FILE REVOKES FROM ONE ROLE ON ONE TABLE, AND THAT IS DELIBERATE
-- ----------------------------------------------------------------------------
-- sql/04 carries `REVOKE ALL ON ALL TABLES IN SCHEMA synapse FROM
-- synapse_reader`, which twice stripped privileges a later migration had granted.
-- This file is narrower still than 06, 07 and 08: it names one role AND one
-- table, so it cannot strip anything from axon_sender, axon_reader or
-- axon_tenant_reader, and cannot strip user_admin_backend's own access to the
-- core schema either, whatever a future migration grants.
-- ============================================================================


-- ---------- Schema usage ------------------------------------------------------
-- USAGE only. Not CREATE: CM does not own this schema and must not be able to add
-- objects to it. Axon's Alembic chain is the only thing that shapes axon.
GRANT USAGE ON SCHEMA axon TO user_admin_backend;


-- ---------- Narrow first ------------------------------------------------------
--
-- The only statement here that can REMOVE a privilege somebody added by hand.
-- Scoped to this role AND this table, so re-running narrows exactly this pairing
-- back to the posture below and the verification block proves it did.
REVOKE ALL ON axon.channel_connections FROM user_admin_backend;


-- ---------- The three verbs ---------------------------------------------------
-- SELECT for both reads and for the upsert's arbiter. INSERT and UPDATE for the
-- upsert's two halves. See the header for why there is no DELETE.
GRANT SELECT, INSERT, UPDATE ON axon.channel_connections TO user_admin_backend;


-- ---------- Explicitly NOT granted -------------------------------------------
-- Stated as SQL rather than as a comment, because a comment cannot fail. If a
-- later migration or a hand-run grants any of these, re-running this file takes
-- them away again and the verification below reports the corrected posture.
REVOKE DELETE, TRUNCATE, REFERENCES, TRIGGER ON axon.channel_connections
    FROM user_admin_backend;

-- The template registry is not CM's. It ships empty and ungranted.
REVOKE ALL ON axon.channel_templates FROM user_admin_backend;

-- The delivery ledgers are not CM's either. CM records that a channel is
-- configured; what was actually sent is Axon's evidence and is read through
-- axon_reader by the operator console.
REVOKE ALL ON axon.platform_deliveries FROM user_admin_backend;
REVOKE ALL ON axon.tenant_deliveries   FROM user_admin_backend;


-- ============================================================================
-- VERIFY. RUN THIS AND READ IT; a grant file that is not checked is a claim.
--
-- THE POSTURE IS SET EXPLICITLY BELOW AND THAT IS NOT CEREMONY. The second query
-- reads a FORCE RLS table. Without app.user_type it returns zero rows and raises
-- nothing, and "0" would read as "the grant works and nothing is configured"
-- when it might equally mean "the posture is wrong and this proves nothing".
-- ============================================================================

-- 1. THE PRIVILEGE SET, EXACTLY. Expect three rows: SELECT, INSERT, UPDATE.
--    Any DELETE, TRUNCATE, REFERENCES or TRIGGER row means the REVOKE above did
--    not run or something re-granted it afterwards.
SELECT privilege_type
FROM information_schema.table_privileges
WHERE grantee    = 'user_admin_backend'
  AND table_schema = 'axon'
  AND table_name   = 'channel_connections'
ORDER BY privilege_type;

-- 2. THE POSTURE, STATED. A PLATFORM session must be able to count every tenant's
--    rows. Run these three together: the count is only meaningful because the two
--    set_config calls above it ran in the same session.
SELECT set_config('app.user_type', 'PLATFORM', false);
SELECT set_config('app.tenant_id', '', false);
SELECT count(*) AS rows_visible_to_a_platform_session FROM axon.channel_connections;

-- 3. THE TABLES THIS ROLE MUST NOT REACH. Expect ZERO rows. A row here is a
--    credential-adjacent privilege nobody asked for.
SELECT table_name, privilege_type
FROM information_schema.table_privileges
WHERE grantee      = 'user_admin_backend'
  AND table_schema = 'axon'
  AND table_name  IN ('channel_templates', 'platform_deliveries', 'tenant_deliveries')
ORDER BY table_name, privilege_type;
