-- ============================================================================
-- DIS telemetry schema: connector_health  (Connector Health Phase A, D116)
--
-- The first WORKER-PRODUCED telemetry table in the shared DIS DB. It resolves
-- the deferral D112 flagged: connector health (last-seen, missed intervals,
-- rate limit, auth expiry) is worker/poller-produced telemetry, not a BFF write.
-- One row per (tenant_id, source_id) — the per-connector liveness/freshness record.
--
-- Producer/consumer split (the inverse of config.sources, which is BFF-written):
--   - WRITTEN by the ingress workers. services/csv-ingest-worker emits per run
--     (last_seen_at + status='healthy' on a successful arrival; last_error_at /
--     last_error_detail + status='stale' on a failed run) via an idempotent
--     INSERT ... ON CONFLICT (tenant_id, source_id) DO UPDATE, on a libs/dis-rls
--     rls_session connection — the SAME two-GUC / WITH CHECK / no-.commit()
--     discipline as the bronze write (hard rules 1 & 12). Additive to the
--     pipeline and fire-and-forget (a health-emit failure never blocks ingest).
--     The 3 deferred receivers (api/webhook, reverse-api, csv-erp/SFTP) have no
--     producer yet — their connectors render pending on the surface until built.
--   - READ (read-only) by services/dis-ui-server GET /connector-health, LEFT
--     JOINed from config.sources (connector identity) and coalesced with the
--     bronze MAX(received_at) so an active connector shows freshness even before
--     the worker has emitted a health row.
--
-- STANDALONE in Phase A: no FK from source_id to config.sources (join at read —
-- same deferral rationale as config.sources' standalone source_id). NO backfill
-- (health is live-emitted, not reconstructable). All signal columns are NULLABLE:
-- a given arrival method emits only what it has.
--
-- ----------------------------------------------------------------------------
-- Dependencies
-- ----------------------------------------------------------------------------
--   - schema: telemetry (created by migration 0016; NOT in the 0001 manifest)
--   - schema: identity_mirror, with table tenants
-- ============================================================================


CREATE TABLE telemetry.connector_health (

    -- ---------- Identity ----------
    tenant_id                   UUID                                NOT NULL,
    source_id                   VARCHAR(128) COLLATE "C"            NOT NULL,
        -- The connector's source slug. Same value carried on config.sources.source_id
        -- and config.source_mappings.source_id (no FK in Phase A — joined at read).

    -- ---------- Liveness / freshness (worker-emitted; all NULLABLE) ----------
    last_seen_at                TIMESTAMPTZ                         NULL,
        -- Last successful arrival for this connector (worker stamps now() on a
        -- successful run). NULL until the worker has emitted once. The BFF read
        -- COALESCEs this with the bronze MAX(received_at) so freshness shows pre-emission.
    last_error_at               TIMESTAMPTZ                         NULL,
        -- Last failed run (e.g. preflight failure). NULL when none seen.
    last_error_detail           TEXT                                NULL,
        -- Coarse, non-PII failure reason (e.g. preflight reason code). Never payload.
    auth_expires_at             TIMESTAMPTZ                         NULL,
        -- Credential expiry for connectors with auth (poller/receiver-produced).
        -- No CSV producer sets it; drives the read-derived 'auth_expiring' status.
    rate_limit_state            TEXT                                NULL,
        -- Coarse rate-limit posture (poller-produced). NULL when N/A. Presence
        -- drives the read-derived 'rate_limited' status.
    missed_intervals            INTEGER                             NULL,
        -- Consecutive missed scheduled intervals. Requires a machine cadence to
        -- compute; NULL in Phase A (config.sources.schedule is a human label only).

    -- ---------- Coarse worker status (a hint; the BFF read is authoritative) ----------
    status                      TEXT         COLLATE "C"            NULL,
        -- Worker's coarse hint: 'healthy' on a successful arrival, 'stale' on a
        -- failed run. The surface's displayed status is DERIVED ON READ from the
        -- signals above (auth/rate-limit/freshness), falling back to 'pending' where
        -- there is no producer and no activity. NULL until the worker emits.

    -- ---------- DIS-managed ----------
    updated_at                  TIMESTAMPTZ                         NOT NULL DEFAULT NOW(),
    metadata                    JSONB                               NULL,

    -- ---------- Primary key ----------
    CONSTRAINT pk_telemetry_connector_health
        PRIMARY KEY (tenant_id, source_id),

    -- ---------- Foreign key ----------
    CONSTRAINT fk_telemetry_connector_health_tenant
        FOREIGN KEY (tenant_id)
        REFERENCES identity_mirror.tenants (tenant_id),

    -- ---------- Check constraints ----------
    CONSTRAINT ck_telemetry_connector_health_status_vocab
        CHECK (status IS NULL OR status IN
            ('healthy', 'stale', 'auth_expiring', 'rate_limited', 'pending'))
);


-- ----------------------------------------------------------------------------
-- Indexes (beyond PK)
-- ----------------------------------------------------------------------------

-- Tenant-scoped listing (the BFF read joins config.sources per tenant).
CREATE INDEX ix_telemetry_connector_health_tenant
    ON telemetry.connector_health (tenant_id);


-- ----------------------------------------------------------------------------
-- Row-Level Security — two-GUC (D91), matching config.sources
-- ----------------------------------------------------------------------------
-- TENANT sees/writes its own tenant; PLATFORM (app.user_type='PLATFORM') reads
-- all tenants (USING) but the WITH CHECK stays tenant-pinned, so a worker write
-- can only land in the event's own tenant (the structural backstop the worker
-- write-isolation test proves).

ALTER TABLE telemetry.connector_health ENABLE ROW LEVEL SECURITY;
ALTER TABLE telemetry.connector_health FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation
    ON telemetry.connector_health
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        OR current_setting('app.user_type', true) = 'PLATFORM'
    )
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);


-- ----------------------------------------------------------------------------
-- Comments
-- ----------------------------------------------------------------------------

COMMENT ON TABLE telemetry.connector_health IS
'Per-connector liveness/freshness telemetry (Phase A, D116). One row per (tenant_id, source_id). WORKER-WRITTEN (csv-ingest-worker emits per run via rls_session, WITH CHECK tenant-pinned); dis-ui-server GET /connector-health reads it read-only, joined to config.sources and coalesced with bronze MAX(received_at). Standalone in Phase A (no FK to config.sources). Two-GUC RLS. Inverse producer of config.sources.';

COMMENT ON COLUMN telemetry.connector_health.status IS
'Coarse worker hint (healthy on success, stale on failed run). The surface status is DERIVED ON READ from last_seen_at freshness, auth_expires_at, rate_limit_state — pending where no producer/activity.';

COMMENT ON COLUMN telemetry.connector_health.missed_intervals IS
'Consecutive missed scheduled intervals. NULL in Phase A — requires a machine cadence; config.sources.schedule is a human label only.';
