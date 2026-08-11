-- ============================================================================
-- axon.platform_deliveries + axon.tenant_deliveries: the delivery ledger.
--
-- ONE LEDGER, TWO PHYSICAL TABLES, SPLIT BY AUDIENCE. Every column is identical
-- across the pair except one: tenant_deliveries carries tenant_id NOT NULL and
-- platform_deliveries has no such column at all.
--
-- WHY A SPLIT RATHER THAN ONE TABLE WITH A NULLABLE tenant_id. This repository
-- has already built the nullable-tenant_id shape once and then spent a slice
-- undoing it: Customer Master's user_role_assignments carried an IS-NULL-gated
-- RLS policy until Step 6.8.1 split it into platform_* and tenant_* tables, and
-- its D-34 records the two structural side effects that forced the split. A
-- PLATFORM session could not read the whole table in one query, and cross-tenant
-- injection prevention had to live in application code rather than in the schema.
-- CM's audit log is the second instance of the same split and is the closest
-- precedent to this file: core.tenant_activity_audit_logs and
-- core.platform_activity_audit_logs are a symmetric pair, one RLS'd and one not.
--
-- WHERE THIS PAIR DIVERGES FROM THAT PRECEDENT, and it is deliberate: CM's
-- platform table keeps a NULLABLE tenant_id, populated on a few row kinds. This
-- one has no tenant_id column. A platform delivery has no tenant by
-- construction, and a permanently-NULL column invites a write that means
-- nothing while looking meaningful.
--
-- ----------------------------------------------------------------------------
-- THE SUBJECT IS AN OPAQUE (kind, id) PAIR, NEVER A FOREIGN KEY
-- ----------------------------------------------------------------------------
-- subject_kind + subject_id say what a delivery was ABOUT. They are text, they
-- reference nothing, and there is no FK into synapse.actions or anywhere else.
--
-- Axon is a delivery plane, not a Synapse appendage. An FK would make that claim
-- false in the schema whatever the comments said: it would order the two chains
-- against each other, it would make a Synapse row undeletable because a delivery
-- mentions it, and it would mean a second producer needs a second nullable FK
-- column. The pair costs one join that nothing currently performs and buys a
-- module boundary that is real rather than asserted.
--
-- It is also what lets ONE send refer to MANY findings without a schema change.
-- A per-alert message and a daily digest are the same row shape under this
-- scheme; under an FK they are not.
--
-- ----------------------------------------------------------------------------
-- accepted IS NOT sent, AND THE STATE NAME IS THE GUARD
-- ----------------------------------------------------------------------------
-- A provider returning its success code has ACCEPTED the message for delivery.
-- It has not delivered it. SendGrid answers 202; the mail may still bounce, be
-- filtered, or be dropped, and nothing in this platform will know.
--
-- So the terminal state reachable today is `accepted`. Naming it `sent` would
-- make every future reader of this table believe something the table cannot
-- support. Only an inbound delivery-receipt webhook can move a row past
-- accepted, and that plane does not exist yet: when it does, it brings the
-- states it can produce AND the UPDATE grant a transition needs.
-- ============================================================================


CREATE SCHEMA IF NOT EXISTS axon;


-- ----------------------------------------------------------------------------
-- The platform ledger: Sevyn8's own traffic. Email only, and that is a CHECK.
-- ----------------------------------------------------------------------------
--
-- EMAIL ONLY IS EXPRESSED AS A CONSTRAINT RATHER THAN A CONVENTION, and the
-- reason is the one synapse.provision's rung already made: a value that cannot
-- be written cannot be mistyped. Sevyn8's own platform traffic goes out on
-- Sevyn8's own SendGrid credential. It has no WhatsApp Business account, no DLT
-- registration and no approved templates, because those belong to a TENANT and
-- this table is not tenant traffic. A row here naming any other channel would be
-- a row nothing could send.
--
-- NO ROW LEVEL SECURITY. There is no tenant to isolate. Access is controlled by
-- the grant: axon_sender holds INSERT and nothing else, and no application role
-- holds SELECT. The same posture CM's platform_activity_audit_logs takes.
CREATE TABLE IF NOT EXISTS axon.platform_deliveries (

    -- ---------- Identity ----------
    -- UUIDv7, SUPPLIED BY THE CALLER, never DEFAULT. Two reasons, and the second
    -- is the load-bearing one:
    --
    --   1. uuid4 is banned project-wide; the clock-reading layer mints the id.
    --      Same discipline as synapse.action_events.lifecycle_event_id.
    --   2. RETURNING NEEDS SELECT. The sender holds INSERT and no SELECT at all,
    --      so a server-generated default would leave the writer unable to learn
    --      the id it just wrote without a privilege it must not have. Slice 5e
    --      lost two days to exactly that class of mistake with ON CONFLICT.
    delivery_id             UUID                                NOT NULL,

    created_at              TIMESTAMPTZ                         NOT NULL,

    -- ---------- What was sent, and over what ----------
    channel                 VARCHAR(16) COLLATE "C"             NOT NULL,

    -- What kind of message this is. The vocabulary is the PRODUCER's, not this
    -- table's: a closed CHECK here would mean every new event type is a
    -- migration. It is the join key to the template registry when that exists,
    -- which is why it is a stable slug rather than prose.
    notification_class      VARCHAR(64) COLLATE "C"             NOT NULL,

    -- ---------- The subject: opaque, by design. See the header. ----------
    subject_kind            VARCHAR(32) COLLATE "C"             NOT NULL,
    subject_id              TEXT                                NOT NULL,

    -- The address as actually used. Recorded rather than re-derived: the address
    -- book will change, and a ledger that cannot say where a message actually
    -- went is not a ledger.
    recipient               TEXT                                NOT NULL,

    -- ---------- Outcome ----------
    state                   VARCHAR(16) COLLATE "C"             NOT NULL,

    -- Set exactly when state = 'suppressed'. Paired by CHECK below.
    suppression_reason      VARCHAR(32) COLLATE "C"             NULL,

    provider                VARCHAR(32) COLLATE "C"             NOT NULL,

    -- Why a send failed, for a person diagnosing without the provider console.
    -- Free text: it carries whatever the transport said. NEVER the credential.
    failure_detail          TEXT                                NULL,

    -- ---------- The template that rendered this ----------
    -- ALWAYS NULL HERE, and CHECK-forced so. Platform traffic is free text on
    -- Sevyn8's own credential; there is no approved template because there is no
    -- registered entity and no WABA behind it.
    --
    -- The column exists anyway so the pair keeps ONE column list. A merged read
    -- across both ledgers is then a plain UNION rather than one padded with NULL
    -- literals, which is the property that makes CM's audit pair readable.
    --
    -- ON THE TENANT SIDE IT IS NULLABLE ONLY UNTIL TEMPLATES EXIST. A tenant
    -- message rendered through a DLT or WhatsApp approved template MUST pin the
    -- template version that rendered it, exactly as a canonical row pins
    -- config.source_mappings.mapping_version_id. Without the pin, re-reading an
    -- old delivery renders it with today's template and the record of what was
    -- actually sent is gone. The day the template registry lands, the tenant
    -- table's copy of this column becomes NOT NULL for every channel that
    -- renders through one.
    --
    -- BIGINT, matching config.source_mappings.mapping_version_id's shape, and
    -- deliberately NOT a foreign key: the registry lives in another module and
    -- an FK across that boundary is the coupling subject_kind/subject_id exists
    -- to avoid.
    template_version_id     BIGINT                              NULL,

    -- Who caused this, when a person did. An Auth0 subject, the only honest
    -- identity in the session (synapse.provision's audit line carries the same).
    -- NULL for a delivery no person triggered.
    actor_subject           TEXT                                NULL,

    CONSTRAINT pk_platform_deliveries PRIMARY KEY (delivery_id),

    -- THE EMAIL-ONLY CONSTRAINT. See the header on this table.
    CONSTRAINT ck_platform_deliveries_email_only
        CHECK (channel = 'email'),

    CONSTRAINT ck_platform_deliveries_no_template
        CHECK (template_version_id IS NULL),

    CONSTRAINT ck_platform_deliveries_state_vocab
        CHECK (state IN ('accepted', 'failed', 'suppressed')),

    CONSTRAINT ck_platform_deliveries_suppression_vocab
        CHECK (suppression_reason IS NULL OR suppression_reason IN (
            'no_address', 'channel_not_onboarded', 'consent_withheld', 'no_approved_template'
        )),

    CONSTRAINT ck_platform_deliveries_suppression_pair
        CHECK (
            (state = 'suppressed' AND suppression_reason IS NOT NULL)
            OR
            (state <> 'suppressed' AND suppression_reason IS NULL)
        )
);

COMMENT ON TABLE axon.platform_deliveries IS
'Sevyn8''s own outbound traffic. EMAIL ONLY by CHECK, on Sevyn8''s own SendGrid credential: platform traffic has no WABA, no DLT registration and no approved templates, because those belong to a tenant. No RLS (there is no tenant to isolate); axon_sender holds INSERT and no role holds SELECT. `accepted` means the provider took the message, NOT that it arrived.';

COMMENT ON COLUMN axon.platform_deliveries.subject_kind IS
'What the delivery was about, as an opaque kind. Deliberately not a foreign key: Axon is a delivery plane, not an appendage of whichever module produced the event.';

COMMENT ON COLUMN axon.platform_deliveries.state IS
'accepted | failed | suppressed. `accepted` is ACCEPTANCE BY THE PROVIDER, not delivery; nothing here can observe arrival until an inbound receipt webhook exists.';


-- ----------------------------------------------------------------------------
-- The tenant ledger: multi-channel, and the TENANT is the sender.
-- ----------------------------------------------------------------------------
--
-- SHIPS EMPTY AND UNGRANTED IN THIS SLICE. Nothing writes it: there is no
-- address book, no tenant credential, no approved template and no adapter beyond
-- email. It is built now anyway, for two reasons.
--
--   1. The RLS shape is the hard part, and altering RLS on a table that holds
--      rows is a live-data operation. CM's Step 6.8.1 exists because an RLS
--      shape was chosen early and had to be undone on a populated table.
--   2. Building it now is what forces the USING-versus-WITH-CHECK decision below
--      to be made in daylight rather than by whoever writes the first tenant
--      send under time pressure.
--
-- NO CHANNEL RESTRICTION HERE, and that is the point of the split. Tenant
-- traffic is WhatsApp, SMS and email, sent by the TENANT under the tenant's own
-- WABA, DLT registration and credentials. Legal consent is consent to be
-- contacted by that tenant. None of that exists yet; nothing in this table
-- assumes it does not.
CREATE TABLE IF NOT EXISTS axon.tenant_deliveries (

    -- THE ONE COLUMN THAT DIFFERS FROM THE PLATFORM TABLE.
    tenant_id               UUID                                NOT NULL,

    delivery_id             UUID                                NOT NULL,
    created_at              TIMESTAMPTZ                         NOT NULL,
    channel                 VARCHAR(16) COLLATE "C"             NOT NULL,
    notification_class      VARCHAR(64) COLLATE "C"             NOT NULL,
    subject_kind            VARCHAR(32) COLLATE "C"             NOT NULL,
    subject_id              TEXT                                NOT NULL,
    recipient               TEXT                                NOT NULL,
    state                   VARCHAR(16) COLLATE "C"             NOT NULL,
    suppression_reason      VARCHAR(32) COLLATE "C"             NULL,
    provider                VARCHAR(32) COLLATE "C"             NOT NULL,
    failure_detail          TEXT                                NULL,

    -- Nullable TODAY because no template registry exists. See the platform
    -- table's comment on this column for what it becomes and why it must.
    template_version_id     BIGINT                              NULL,

    actor_subject           TEXT                                NULL,

    CONSTRAINT pk_tenant_deliveries PRIMARY KEY (delivery_id),

    -- The vocabularies are the pair's, identical on both sides. A tenant channel
    -- vocabulary wider than email is what this table exists for, so the CHECK
    -- names the three channels the platform is being built toward rather than
    -- the one it can send today. A row naming a channel with no adapter fails at
    -- the adapter, loudly, not at the database.
    CONSTRAINT ck_tenant_deliveries_channel_vocab
        CHECK (channel IN ('email', 'whatsapp', 'sms')),

    CONSTRAINT ck_tenant_deliveries_state_vocab
        CHECK (state IN ('accepted', 'failed', 'suppressed')),

    CONSTRAINT ck_tenant_deliveries_suppression_vocab
        CHECK (suppression_reason IS NULL OR suppression_reason IN (
            'no_address', 'channel_not_onboarded', 'consent_withheld', 'no_approved_template'
        )),

    CONSTRAINT ck_tenant_deliveries_suppression_pair
        CHECK (
            (state = 'suppressed' AND suppression_reason IS NOT NULL)
            OR
            (state <> 'suppressed' AND suppression_reason IS NULL)
        )
);

COMMENT ON TABLE axon.tenant_deliveries IS
'Tenant-facing outbound traffic, multi-channel. The TENANT is the sender: its own WABA, its own DLT registration, its own credentials, and consent is consent to be contacted by that tenant. Ships EMPTY and UNGRANTED in Axon slice 1; built early because altering RLS on a populated table is a live-data operation.';


-- ----------------------------------------------------------------------------
-- RLS on the tenant ledger. READ the argument before changing the policy.
-- ----------------------------------------------------------------------------
--
-- FORCE, so the policy binds the table owner too. Without FORCE, the owner and
-- any superuser read every tenant's deliveries and the isolation is a property
-- of who happens to connect.
ALTER TABLE axon.tenant_deliveries ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.tenant_deliveries FORCE ROW LEVEL SECURITY;

-- =============================================================================
-- USING AND WITH CHECK ARE DELIBERATELY DIFFERENT. DO NOT "FIX" THIS BACK.
-- =============================================================================
-- USING carries the unconditional PLATFORM branch: a PLATFORM session READS
-- every tenant's deliveries, which is what a fleet-wide operator console needs
-- and what CM's D-29 pattern gives every multi-tenant table in this estate.
--
-- WITH CHECK DOES NOT. A write must name the tenant whose session it is running
-- in. This is where this policy departs from the precedent it otherwise copies:
-- CM's tenant_activity_audit_logs puts the same PLATFORM branch in BOTH halves,
-- so a PLATFORM session there may write a row naming ANY tenant.
--
-- THAT PERMISSIVENESS IS EXACTLY THE BUG A SENDER WOULD PRODUCE. Axon writes on
-- behalf of the platform, in a loop, for many tenants. The failure mode is one
-- delivery recorded against the wrong tenant: it is invisible in the sending
-- path, it lands in another customer's ledger, and under a PLATFORM WITH CHECK
-- nothing anywhere refuses it. Pinning the write to the session's tenant makes
-- that a database refusal instead of a code review.
--
-- The cost is stated so it is not discovered: the first tenant send must open
-- rls_session(engine, tenant_id), NOT rls_platform_session. That is the same
-- shape synapse.provision's policy forces on slice 5e's enable path, and 05's
-- verify block spends two whole sections proving it bites.
--
-- NULLIF(..., '') IS LOAD-BEARING, not decoration. Postgres registers a
-- placeholder GUC at session level on first set_config, so on a REUSED pooled
-- connection current_setting returns '' rather than NULL, and ''::uuid raises.
-- CM paid for this in its migration e59f62d5037d; dis-rls sets the GUC the same
-- way and every policy in this estate wraps it identically.
CREATE POLICY tenant_deliveries_tenant_isolation
    ON axon.tenant_deliveries
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
        OR current_setting('app.user_type', TRUE) = 'PLATFORM'
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
    );


-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------
-- Newest first is how a ledger is read, on both tables.
CREATE INDEX IF NOT EXISTS ix_platform_deliveries_created_at
    ON axon.platform_deliveries (created_at DESC, delivery_id DESC);

CREATE INDEX IF NOT EXISTS ix_tenant_deliveries_tenant_created_at
    ON axon.tenant_deliveries (tenant_id, created_at DESC, delivery_id DESC);

-- The failures, which is what somebody opens this table to find. Partial, so it
-- indexes the small set rather than the whole ledger.
CREATE INDEX IF NOT EXISTS ix_platform_deliveries_not_accepted
    ON axon.platform_deliveries (state)
    WHERE state <> 'accepted';

CREATE INDEX IF NOT EXISTS ix_tenant_deliveries_not_accepted
    ON axon.tenant_deliveries (state)
    WHERE state <> 'accepted';
