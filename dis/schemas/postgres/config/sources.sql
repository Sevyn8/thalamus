-- ============================================================================
-- DIS config schema: sources  (Phase A source registry, D112)
--
-- The first real per-source ENTITY. Before this, "a source" existed only as an
-- implicit source_id string on config.source_mappings rows; there was no source
-- record and no per-source channel/type, which blocked the Upload guard's
-- real-mode ingestion_mode, Data Pipelines' Method, and Connector Health's
-- classification. One row per (tenant_id, source_id).
--
-- Written by:
--   - services/dis-ui-server sources handler (POST /sources) — operator/onboarding
--     source registration. The FIRST writable table dis-ui-server owns in the
--     shared DB. All writes go through libs/dis-rls write_session; the two-GUC
--     WITH CHECK pins every write to the acted-for tenant.
--   - Alembic 0013 backfill (one row per existing distinct source_id).
--
-- Read by:
--   - services/dis-ui-server sources handler (GET /sources) and, later, the Data
--     Pipelines / Connector Health / Upload-guard surfaces.
--
-- STANDALONE in Phase A: no FK from config.source_mappings.source_id to here
-- (deferred — avoids an alter + backfill dependency on the hot config table).
-- Health/runtime fields (last-seen, missed intervals, rate limit, auth expiry)
-- are worker/poller-produced and are a later phase; not modelled here.
--
-- ----------------------------------------------------------------------------
-- Dependencies
-- ----------------------------------------------------------------------------
--   - schema: config
--   - schema: identity_mirror, with table tenants
-- ============================================================================


CREATE TABLE config.sources (

    -- ---------- Identity ----------
    tenant_id                   UUID                                NOT NULL,
    source_id                   VARCHAR(128) COLLATE "C"            NOT NULL,
        -- The registered source slug (e.g. 'shopify_pos_v2', 'manual_csv_upload').
        -- Same value carried on config.source_mappings.source_id (no FK in Phase A).

    -- ---------- Display / classification ----------
    display_name                VARCHAR(256)                        NOT NULL,
    channel                     VARCHAR(32)  COLLATE "C"            NULL,
        -- The ingress channel (api vs file/batch). Reuses the bronze dis_channel
        -- vocabulary. NULL when unknown (backfill found no bronze events for the
        -- source). Drives the Upload guard's ingestion_mode + Data Pipelines Method.
    store_id                    VARCHAR(128) COLLATE "C"            NULL,
        -- Optional store scope (a store code or handle). NULLABLE + no FK in Phase A
        -- (many sources are all-stores; store identity is receiver-resolved, D86).
    schedule                    VARCHAR(128) COLLATE "C"            NULL,
        -- Human cadence label (e.g. 'every 15 min', 'daily 02:00'). Informational.

    -- ---------- Lifecycle ----------
    status                      VARCHAR(32)  COLLATE "C"            NOT NULL DEFAULT 'active',
        -- Operator enablement: active | paused | disabled. NOT the runtime health
        -- (Healthy/Stale/...), which is worker-produced telemetry (later phase).

    -- ---------- Authorship / DIS-managed ----------
    created_by_user_id          UUID                                NULL,
        -- Customer Master user who registered the source. Not a FK (cross-DB).
    created_at                  TIMESTAMPTZ                         NOT NULL DEFAULT NOW(),
    updated_at                  TIMESTAMPTZ                         NOT NULL DEFAULT NOW(),
    metadata                    JSONB                               NULL,

    -- ---------- Primary key ----------
    CONSTRAINT pk_config_sources
        PRIMARY KEY (tenant_id, source_id),

    -- ---------- Foreign key ----------
    CONSTRAINT fk_config_sources_tenant
        FOREIGN KEY (tenant_id)
        REFERENCES identity_mirror.tenants (tenant_id),

    -- ---------- Check constraints ----------
    CONSTRAINT ck_config_sources_channel_vocab
        CHECK (channel IS NULL OR channel IN ('csv_upload', 'api', 'csv_erp', 'reverse_api')),

    CONSTRAINT ck_config_sources_status_vocab
        CHECK (status IN ('active', 'paused', 'disabled'))
);


-- ----------------------------------------------------------------------------
-- Indexes (beyond PK)
-- ----------------------------------------------------------------------------

-- Tenant-scoped listing.
CREATE INDEX ix_config_sources_tenant
    ON config.sources (tenant_id);


-- ----------------------------------------------------------------------------
-- Row-Level Security — two-GUC (D91), matching the other tenant-scoped tables
-- ----------------------------------------------------------------------------
-- TENANT sees/writes its own tenant; PLATFORM (app.user_type='PLATFORM') reads
-- all tenants (USING) but the WITH CHECK stays tenant-pinned, so a write can only
-- land in the acted-for tenant (the structural backstop behind resolve_acted_for).

ALTER TABLE config.sources ENABLE ROW LEVEL SECURITY;
ALTER TABLE config.sources FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation
    ON config.sources
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

COMMENT ON TABLE config.sources IS
'Per-source registry entity (Phase A, D112). One row per (tenant_id, source_id). Written by dis-ui-server POST /sources (operator registration) and the 0013 backfill; the first writable table dis-ui-server owns in the shared DB. Standalone in Phase A (no FK from source_mappings.source_id). Two-GUC RLS.';

COMMENT ON COLUMN config.sources.channel IS
'Ingress channel (api vs file/batch), reusing the bronze dis_channel vocabulary. NULL when unknown. Drives the Upload guard ingestion_mode and Data Pipelines Method.';

COMMENT ON COLUMN config.sources.status IS
'Operator enablement: active | paused | disabled. NOT the runtime connector health (Healthy/Stale/...), which is worker-produced telemetry (later phase).';
