-- ============================================================================
-- axon.channel_connections + axon.channel_templates: the tenant channel rails.
--
-- WHAT THIS FILE IS FOR. Slice 1 built a ledger that can RECORD a tenant send and
-- slice 2 built a queue that can CARRY one. Neither can decide whether a tenant
-- send is possible, and the two questions that decide it are "is this channel
-- connected for this tenant" and "is there an approved template for this class".
-- Those are these two tables.
--
-- FOR TENANT TRAFFIC THE TENANT IS THE SENDER, NEVER SEVYN8. The WhatsApp Business
-- account, the registered sender identity, the credential and the approved
-- templates all belong to the tenant, and a tenant administrator enters them.
-- Sevyn8 never holds or types another company's credential. That is why the
-- credential itself is NOT in this file: only a REFERENCE to it is, and the value
-- lives in Secret Manager under the name recorded in secret_ref.
--
-- WHAT SEVYN8 SUPERADMIN MAY SEE, AND THE LINE IS DRAWN IN THE COLUMN LIST RATHER
-- THAN IN A QUERY. Connection state is operational: it is the answer to "why did
-- that delivery not go out", and an operator who cannot see it is reduced to
-- guessing. The sending identity is an identifier, not a secret, and is visible for
-- the same reason a recipient address is recorded on the ledger. The credential is
-- the tenant's and is not here at all. A future console query is therefore unable
-- to leak one by accident, because there is nothing in these rows to leak.
--
-- ----------------------------------------------------------------------------
-- WHY CONNECTION STATE IS A TABLE AND NOT INFERRED
-- ----------------------------------------------------------------------------
-- DIS infers whether a source is connected from downstream data arriving. That is
-- the right shape there and the wrong shape here, and this file deliberately does
-- not copy it. Two reasons:
--
--   1. THE CONSOLE QUESTION IS A BULK ONE. "Which tenants can receive WhatsApp" is
--      one indexed scan over this table. Against Secret Manager it is one API call
--      per tenant per channel, which is not a query, and against the ledger it is
--      unanswerable: a tenant with no deliveries is indistinguishable from a tenant
--      that cannot receive any.
--   2. AN ABSENCE OF TRAFFIC IS NOT A DISCONNECTION. Inferring state from arriving
--      data means a quiet tenant reads as broken and a broken tenant reads as
--      quiet, and the two need different actions.
--
-- ----------------------------------------------------------------------------
-- NOTHING READS OR WRITES EITHER TABLE IN THIS SLICE, AND THAT IS THE PRECEDENT
-- ----------------------------------------------------------------------------
-- Both ship EMPTY and UNGRANTED, exactly as axon.tenant_deliveries did in slice 1
-- and for the argument 06_axon_sender_grant.sql records: a grant arrives with the
-- code that needs it, together with the session posture that code must open.
-- Granting SELECT to axon_reader now would create a credential reaching tables no
-- code opens a session against, and granting INSERT to anything would create a
-- writer before the surface that writes exists.
--
-- The tables are built now anyway, for slice 1's reason and it has not changed:
-- altering RLS on a populated table is a live-data operation, and the USING versus
-- WITH CHECK decision is better made in daylight than by whoever writes the first
-- tenant send under time pressure.
--
-- ----------------------------------------------------------------------------
-- NOTHING HERE HAS EVER EXECUTED BEFORE STAGING
-- ----------------------------------------------------------------------------
-- Stated because it is true of this file specifically. Axon's suite is offline by
-- design (its Makefile says so, and tests/test_ledger_and_ddl.py's header says what
-- that costs), neither local container carries an axon schema, and so every
-- constraint, every policy and the foreign key below are TEXT-CHECKED here and
-- first EXECUTED by the migrate-axon job. The one exception is the foreign key's
-- cross-tenant behaviour, which was executed against a real Postgres in a scratch
-- schema before this file was written; the result is recorded at that constraint.
-- ============================================================================


-- Idempotent and required by ex_channel_templates_label_per_class below. This must
-- be able to FAIL LOUDLY rather than proceed without the extension: a gist EXCLUDE
-- on a missing operator class is a syntax-level failure, so the CREATE TABLE below
-- is what refuses, and it refuses in the same transaction as this statement.
CREATE EXTENSION IF NOT EXISTS btree_gist;


-- ----------------------------------------------------------------------------
-- axon.channel_connections: can this tenant send on this channel, and as whom.
-- ----------------------------------------------------------------------------
--
-- ONE ROW PER TENANT PER CHANNEL, AND THE PRIMARY KEY SAYS SO. A second row for the
-- same pair would make "is WhatsApp connected for this tenant" a question with two
-- answers, and the console reads it in bulk precisely so that it has one.
--
-- ============================================================================
-- READ THIS BEFORE WRITING THE FIRST UPSERT. ON CONFLICT NEEDS SELECT.
-- ============================================================================
-- The natural writer for this table is an upsert on (tenant_id, channel): a tenant
-- administrator saves the form twice and the second save must update rather than
-- fail. ON CONFLICT reads the ARBITER INDEX, which is a SELECT privilege on this
-- table, and axon_sender holds no SELECT anywhere by deliberate design.
--
-- THAT EXACT MISTAKE COST SLICE 5e TWO DAYS of every enable in production failing
-- with `permission denied` behind a green apply, and 06_axon_sender_grant.sql
-- records it in full along with the two mechanisms that work: catch SQLSTATE 23505
-- matched TOGETHER WITH the constraint name, or deduplicate before the write.
--
-- Whichever the writing slice chooses, it must choose it WITH its grant, in that
-- slice. A writer added first and a grant added afterwards is the failure this
-- comment exists to prevent, and it will not announce itself in a plan.
-- ============================================================================
CREATE TABLE IF NOT EXISTS axon.channel_connections (

    tenant_id           UUID                                NOT NULL,

    -- SAME WIDTH AND SAME VOCABULARY AS THE LEDGER'S COLUMN, not a second one. A
    -- narrower column here would make a channel the ledger can record into one this
    -- table cannot describe, and the join between them would silently truncate.
    channel             VARCHAR(16) COLLATE "C"             NOT NULL,

    -- Who carries it. Sinch for the first tenant, and the column is text rather
    -- than a CHECK because provider choice is per-tenant configuration: a closed
    -- vocabulary here would make every new carrier a migration.
    provider            VARCHAR(32) COLLATE "C"             NOT NULL,

    status              VARCHAR(16) COLLATE "C"             NOT NULL,

    -- THE SENDING IDENTITY, AND IT IS AN IDENTIFIER RATHER THAN A SECRET. A phone
    -- number, a sender id, a WABA display number: the thing a recipient sees in the
    -- from field. Superadmin-visible for the same reason the ledger records the
    -- recipient it actually used.
    --
    -- NULLABLE because a connection can exist before the provider has issued one.
    sending_identity    TEXT                                NULL,

    -- THE SECRET's NAME, NEVER ITS VALUE AND NEVER A VERSION.
    --
    -- WRITTEN BY THE WRITER, READ VERBATIM BY THE READER, DERIVED BY NOBODY ELSE.
    -- Slice 4 said both sides would derive it from a shared axon.vault helper. That
    -- helper was deleted in slice 5: Customer Master is the writer and cannot import
    -- this package (not a uv workspace member, and its Dockerfile builds from
    -- cm-backend/ with no path to axon/), so a shared function had one caller and
    -- would have become two definitions free to disagree. CM derives the name and
    -- stores it here; Axon reads this column and never derives.
    --
    -- CM'S DERIVATION IS STILL DETERMINISTIC, AND THAT IS NOT STYLE. The Secret
    -- Manager write and this row's write cannot be atomic. If the secret lands and
    -- the row does not, a free-form name orphans a live tenant credential that
    -- nothing can attribute to a tenant or a channel ever again. A deterministic
    -- name makes the retry land on the same secret, and makes an orphan readable.
    --
    -- A VERSION IS DELIBERATELY NOT RECORDED. Pinning one here would make this row
    -- go stale the moment a credential is rotated, and the reader wants "latest"
    -- rather than "whatever was current when the row was written".
    secret_ref          TEXT                                NULL,

    -- Paired to status by CHECK, the shape config.source_mappings uses for its
    -- lifecycle. A timestamp that can disagree with the status it describes is a
    -- second source of truth about the same fact.
    connected_at        TIMESTAMPTZ                         NULL,
    disabled_at         TIMESTAMPTZ                         NULL,

    created_at          TIMESTAMPTZ                         NOT NULL,
    updated_at          TIMESTAMPTZ                         NOT NULL,

    CONSTRAINT pk_channel_connections PRIMARY KEY (tenant_id, channel),

    CONSTRAINT ck_channel_connections_channel_vocab
        CHECK (channel IN ('email', 'whatsapp', 'sms')),

    -- ONLY 'pending' IS REACHABLE TODAY, AND THE NAME IS THE GUARD.
    --
    -- 'connected' means a send was ACCEPTED on this channel. No adapter beyond
    -- email exists, so nothing in this repository can observe that yet and nothing
    -- may write it. This is the same discipline the ledger applies in refusing to
    -- call its terminal state `sent`: a state named for something the system cannot
    -- observe teaches every future reader something false.
    --
    -- 'disabled' arrives with whichever surface can turn a channel off, tenant-side
    -- or Sevyn8-side. It is named now because naming the next member is what makes
    -- the paired CHECK below testable before there is a writer.
    CONSTRAINT ck_channel_connections_status_vocab
        CHECK (status IN ('pending', 'connected', 'disabled')),

    CONSTRAINT ck_channel_connections_connected_pair
        CHECK (
            (status = 'connected' AND connected_at IS NOT NULL)
            OR
            (status <> 'connected' AND connected_at IS NULL)
        ),

    CONSTRAINT ck_channel_connections_disabled_pair
        CHECK (
            (status = 'disabled' AND disabled_at IS NOT NULL)
            OR
            (status <> 'disabled' AND disabled_at IS NULL)
        )
);

COMMENT ON TABLE axon.channel_connections IS
'Per tenant per channel: whether the tenant can send, as which identity, and which Secret Manager name holds its credential. The CREDENTIAL IS NOT HERE, only its name: the credential belongs to the tenant and Sevyn8 never holds one. Connection state is a TABLE rather than inferred from secret existence or from traffic, because the console question is a bulk one and an absence of traffic is not a disconnection.';

COMMENT ON COLUMN axon.channel_connections.status IS
'pending | connected | disabled. Only `pending` is reachable today: `connected` means a send was accepted on this channel and no adapter beyond email exists to accept one.';

-- LEDGER ITEM, DELIBERATELY NOT SYNCED IN SLICE 5. The COMMENT below is corrected in
-- this file, but the LIVE comment in staging still reads "from axon.vault.secret_id_for",
-- because migration 0002 already applied the old text and updating it needs a new axon
-- revision, which needs a synapse-ui-server image rebuild (that image is what migrate-axon
-- runs). A console BFF deploy to fix a metadata string is the wrong trade, and it would be
-- the fourth instance of that shared-image coupling. THE NEXT AXON MIGRATION THAT SHIPS FOR
-- A REAL REASON MUST CARRY THIS ONE STATEMENT.
COMMENT ON COLUMN axon.channel_connections.secret_ref IS
'The Secret Manager secret NAME. Never the value, and deliberately not a version: pinning a version would make this row stale on the first rotation. Written by Customer Master, read verbatim by Axon, derived by nobody else.';


-- RLS. Copied VERBATIM from axon.tenant_deliveries, including the asymmetry.
ALTER TABLE axon.channel_connections ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.channel_connections FORCE ROW LEVEL SECURITY;

-- =============================================================================
-- USING AND WITH CHECK ARE DELIBERATELY DIFFERENT. DO NOT "FIX" THIS BACK.
-- =============================================================================
-- The full argument lives in deliveries.sql at tenant_deliveries_tenant_isolation
-- and is not repeated. What matters here is that it applies for the SAME reason:
-- a PLATFORM session must READ every tenant's connection state, because that is
-- the fleet-wide operator question this table exists to answer, and a PLATFORM
-- session must not WRITE a row naming an arbitrary tenant, because the writer will
-- be a loop over tenants and the failure mode is one tenant's credential reference
-- recorded against another tenant.
--
-- config.source_mappings carries the same asymmetry, which is also the table Part C
-- below is modelled on, so all three agree.
--
-- NULLIF(..., '') IS LOAD-BEARING. A pooled connection that has already had
-- set_config called on it returns '' rather than NULL, and ''::uuid raises.
--
-- DROPPED FIRST, BECAUSE `CREATE POLICY IF NOT EXISTS` DOES NOT EXIST. This was found by
-- running the file twice rather than by reading it: the second run failed with
-- `policy "..." for table "..." already exists`. Every DDL file in this chain is
-- required to be hand-runnable and repeatable (0001's contract), and CREATE TABLE
-- IF NOT EXISTS is not enough on its own to deliver that when a policy follows.
DROP POLICY IF EXISTS channel_connections_tenant_isolation ON axon.channel_connections;
CREATE POLICY channel_connections_tenant_isolation
    ON axon.channel_connections
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
        OR current_setting('app.user_type', TRUE) = 'PLATFORM'
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
    );

-- THE BULK CONSOLE QUESTION, INDEXED. "Which tenants can receive WhatsApp" reads
-- (channel, status) across every tenant, which the primary key cannot serve
-- because tenant_id leads it.
CREATE INDEX IF NOT EXISTS ix_channel_connections_channel_status
    ON axon.channel_connections (channel, status);


-- ----------------------------------------------------------------------------
-- axon.channel_templates: which approved template name renders which class.
-- ----------------------------------------------------------------------------
--
-- SHAPED ON config.source_mappings, WHICH IS FULLY WORKED OUT. That table solved
-- the same problem one plane over: a per-tenant configuration artifact that is
-- edited over time, where a row already used by a produced record must never
-- change underneath it. Everything below that looks elaborate is load-bearing there
-- and is carried for the reason it was learned, not for symmetry.
--
--   stable id vs editable label   template_id never changes and is what versions of
--                                 one template share; template_label is what an
--                                 operator renames without breaking lineage.
--   DRAFT/STAGED/ACTIVE/DEPRECATED  with the two timestamps CHECK-paired to it.
--   immutable rows                 an edit INSERTS a new version and points
--                                  predecessor_version_id at the old one.
--   at most one ACTIVE             a partial unique index, not application code.
--
-- IT KEYS ON A NAME STRING, AND THE REGISTRY SHIPS EMPTY. provider_template_name is
-- the approved name at the provider, and no row is seeded: three names exist for the
-- first tenant and none of them can be verified until an adapter can attempt a send.
-- A seeded name that turns out to be wrong is worse than an empty table, because an
-- empty table suppresses with a reason and a wrong name fails at the provider.
--
-- 'no_approved_template' ALREADY EXISTS IN BOTH SUPPRESSION VOCABULARIES, on
-- axon.platform_deliveries and axon.tenant_deliveries alike, and nothing is added
-- here. IT IS CURRENTLY UNREACHABLE: nothing in axon/src/axon/send.py can emit it,
-- because there is no registry to miss. THIS TABLE IS WHAT MAKES IT REACHABLE, and
-- the slice that teaches the send path to resolve a template is the slice in which
-- that reason starts appearing in the ledger.
CREATE TABLE IF NOT EXISTS axon.channel_templates (

    -- ---------- Surrogate key ----------
    -- Monotonic across all tenants. This is the FK target that axon.tenant_deliveries
    -- pins, exactly as canonical rows pin config.source_mappings.mapping_version_id,
    -- and BIGINT matches the ledger column that already exists to receive it.
    template_version_id     BIGSERIAL                           NOT NULL,

    -- ---------- Identity ----------
    tenant_id               UUID                                NOT NULL,

    -- Same width and vocabulary as the ledger's column. See channel_connections.
    channel                 VARCHAR(16) COLLATE "C"             NOT NULL,

    -- THE JOIN KEY TO THE LEDGER, at the ledger's own width. deliveries.sql calls
    -- notification_class "the join key to the template registry when that exists",
    -- and this is that registry, so the two columns are the same shape on purpose.
    notification_class      VARCHAR(64) COLLATE "C"             NOT NULL,

    -- Stable identity of one template across its versions. UUIDv7, minted by the
    -- writing surface at DRAFT creation and immutable thereafter, which is a
    -- write-path convention here exactly as it is in config.source_mappings.
    template_id             UUID                                NOT NULL,

    -- The operator's own label, editable. Unique per (tenant, channel, class) among
    -- non-DEPRECATED rows, by EXCLUDE rather than by unique index. See that
    -- constraint for why the distinction is not pedantry.
    template_label          TEXT COLLATE "C"                    NOT NULL,

    -- THE NAME STRING THIS REGISTRY EXISTS FOR: the approved template's name at the
    -- provider. Text, because the approval process is outside this repository and
    -- nothing here can validate the shape of a name it did not issue.
    provider_template_name  TEXT COLLATE "C"                    NOT NULL,

    -- Per (tenant, channel, class, template) sequence. Set by trigger on INSERT.
    version_seq             SMALLINT                            NOT NULL,

    -- ---------- Status ----------
    status                  TEXT COLLATE "C"                    NOT NULL,

    -- ---------- Lineage ----------
    -- The version this one was edited from. NULL for a template's first version.
    -- NOT a self-referencing foreign key, and config.source_mappings' predecessor
    -- column made the same call for the same reason: it is informational for
    -- operators and enforcing it buys nothing, while an FK would order deletes.
    predecessor_version_id  BIGINT                              NULL,

    -- ---------- Lifecycle timestamps ----------
    activated_at            TIMESTAMPTZ                         NULL,
    deprecated_at           TIMESTAMPTZ                         NULL,

    -- ---------- Authorship ----------
    -- AN AUTH0 SUBJECT, WHICH IS A DIVERGENCE FROM THE PRECEDENT AND IS DELIBERATE.
    -- config.source_mappings carries created_by_user_id UUID. Axon records people as
    -- actor_subject on both ledgers, and deliveries.sql calls that "the only honest
    -- identity in the session". Consistency inside this module beats copying a
    -- column type across one, and a UUID here would need a lookup the delivery plane
    -- has no reason to be able to perform.
    created_by_subject      TEXT                                NULL,

    created_at              TIMESTAMPTZ                         NOT NULL DEFAULT NOW(),

    -- Free-form: approval reference, change note, provider response. Designed to
    -- evolve, same role as config.source_mappings.metadata.
    metadata                JSONB                               NULL,

    CONSTRAINT pk_channel_templates PRIMARY KEY (template_version_id),

    -- ========================================================================
    -- THE COMPOSITE FOREIGN KEY'S TARGET. Redundant-looking and load-bearing.
    -- ========================================================================
    -- template_version_id is already unique on its own as the primary key, so this
    -- constraint adds no uniqueness. What it adds is a REFERENCEABLE (tenant_id,
    -- template_version_id) pair, which is the only thing a two-column foreign key
    -- can point at. Without it the ALTER at the foot of this file cannot be written.
    CONSTRAINT uq_channel_templates_tenant_version
        UNIQUE (tenant_id, template_version_id),

    CONSTRAINT uq_channel_templates_version_seq
        UNIQUE (tenant_id, channel, notification_class, template_id, version_seq),

    CONSTRAINT ck_channel_templates_status_vocab
        CHECK (status IN ('DRAFT', 'STAGED', 'ACTIVE', 'DEPRECATED')),

    CONSTRAINT ck_channel_templates_version_seq_positive
        CHECK (version_seq > 0),

    CONSTRAINT ck_channel_templates_channel_vocab
        CHECK (channel IN ('email', 'whatsapp', 'sms')),

    CONSTRAINT ck_channel_templates_activated_consistency
        CHECK (
            (status NOT IN ('ACTIVE', 'DEPRECATED') AND activated_at IS NULL)
            OR
            (status IN ('ACTIVE', 'DEPRECATED') AND activated_at IS NOT NULL)
        ),

    CONSTRAINT ck_channel_templates_deprecated_consistency
        CHECK (
            (status <> 'DEPRECATED' AND deprecated_at IS NULL)
            OR
            (status = 'DEPRECATED' AND deprecated_at IS NOT NULL)
        ),

    -- ------------------------------------------------------------------------
    -- LABEL UNIQUENESS, AND WHY IT IS AN EXCLUDE RATHER THAN A UNIQUE INDEX
    -- ------------------------------------------------------------------------
    -- A plain unique index on (tenant, channel, class, label) would forbid the
    -- NORMAL case this table exists to support: during a shadow rollout an ACTIVE
    -- v1 and a STAGED v2 of ONE template legitimately share a label. A guard that
    -- refuses the normal case is worse than no guard, because it gets removed.
    --
    -- So only rows with a DIFFERENT template_id may conflict on a label, which is
    -- exactly what a gist EXCLUDE with `template_id WITH <>` expresses and what a
    -- unique index cannot. DEPRECATED frees a label for reuse, mirroring how the
    -- partial unique index below frees the ACTIVE slot.
    --
    -- Lifted from config.source_mappings' ex_csm_template_name_per_source, which
    -- needs btree_gist for the equality operator classes; the CREATE EXTENSION at
    -- the head of this file is that dependency and is not optional.
    CONSTRAINT ex_channel_templates_label_per_class
        EXCLUDE USING gist (
            tenant_id WITH =,
            channel WITH =,
            notification_class WITH =,
            template_label WITH =,
            template_id WITH <>
        ) WHERE (status <> 'DEPRECATED')
);

COMMENT ON TABLE axon.channel_templates IS
'Per tenant, per channel, per notification class: which approved provider template name renders it. Shaped on config.source_mappings: stable template_id versus editable template_label, DRAFT/STAGED/ACTIVE/DEPRECATED with CHECK-paired timestamps, immutable rows with predecessor lineage, and at most one ACTIVE per resolution key. SHIPS EMPTY and stays empty until an adapter can verify a send.';

COMMENT ON COLUMN axon.channel_templates.provider_template_name IS
'The approved template name at the provider. Text, because the approval process is outside this repository and nothing here can validate a name it did not issue.';


-- ----------------------------------------------------------------------------
-- AT MOST ONE ACTIVE, AND THE KEY DIFFERS FROM THE PRECEDENT ON PURPOSE
-- ----------------------------------------------------------------------------
-- config.source_mappings keys its equivalent index on (tenant_id, source_id,
-- template_id): one ACTIVE version PER TEMPLATE. That is right there, because a
-- source can carry several templates at once and each resolves independently.
--
-- HERE THE RESOLUTION QUESTION IS DIFFERENT, and the index has to match the
-- question rather than the precedent. The send path will ask "given this tenant,
-- this channel and this notification class, which approved name do I use", and that
-- must have ONE answer. Keying on template_id would permit two ACTIVE rows for one
-- (tenant, channel, class) as long as they belonged to different templates, which
-- is precisely the ambiguity the send path cannot resolve.
CREATE UNIQUE INDEX IF NOT EXISTS uq_channel_templates_active_per_class
    ON axon.channel_templates (tenant_id, channel, notification_class)
    WHERE status = 'ACTIVE';

CREATE INDEX IF NOT EXISTS ix_channel_templates_tenant_channel_status
    ON axon.channel_templates (tenant_id, channel, status);

CREATE INDEX IF NOT EXISTS ix_channel_templates_predecessor
    ON axon.channel_templates (predecessor_version_id)
    WHERE predecessor_version_id IS NOT NULL;


-- The per-template version counter, set server-side so no writer has to read the
-- current maximum and race another writer between the read and the insert. Same
-- shape and same reason as config.set_csm_version_seq.
CREATE OR REPLACE FUNCTION axon.set_channel_template_version_seq()
RETURNS TRIGGER AS $$
BEGIN
    IF NEW.version_seq IS NULL OR NEW.version_seq = 0 THEN
        SELECT COALESCE(MAX(version_seq), 0) + 1
        INTO NEW.version_seq
        FROM axon.channel_templates
        WHERE tenant_id = NEW.tenant_id
          AND channel = NEW.channel
          AND notification_class = NEW.notification_class
          AND template_id = NEW.template_id;
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_channel_templates_set_version_seq ON axon.channel_templates;
CREATE TRIGGER trg_channel_templates_set_version_seq
    BEFORE INSERT ON axon.channel_templates
    FOR EACH ROW
    EXECUTE FUNCTION axon.set_channel_template_version_seq();


-- RLS. Copied VERBATIM from axon.tenant_deliveries, including the asymmetry. The
-- argument is at that policy and at channel_connections above; it is the same one.
ALTER TABLE axon.channel_templates ENABLE ROW LEVEL SECURITY;
ALTER TABLE axon.channel_templates FORCE ROW LEVEL SECURITY;

-- Dropped first for the same reason as channel_connections' policy above.
DROP POLICY IF EXISTS channel_templates_tenant_isolation ON axon.channel_templates;
CREATE POLICY channel_templates_tenant_isolation
    ON axon.channel_templates
    FOR ALL
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
        OR current_setting('app.user_type', TRUE) = 'PLATFORM'
    )
    WITH CHECK (
        tenant_id = NULLIF(current_setting('app.tenant_id', TRUE), '')::uuid
    );


-- ============================================================================
-- THE COMPOSITE FOREIGN KEY ON axon.tenant_deliveries.
--
-- WHY IT IS TWO COLUMNS, AND THIS IS A MEASUREMENT RATHER THAN A GENERAL CLAIM
-- ABOUT SAFETY. Both forms were built in a scratch schema against a real Postgres,
-- with both tables FORCE ROW LEVEL SECURITY under this exact policy, and written to
-- by a role that was NOSUPERUSER NOBYPASSRLS and held INSERT and no SELECT:
--
--   SINGLE COLUMN, REFERENCES axon.channel_templates (template_version_id):
--     a delivery row belonging to tenant A, inserted in a session whose
--     app.tenant_id was tenant A, successfully referenced a template version
--     belonging to tenant B. The INSERT was ACCEPTED. Referential-integrity checks
--     bypass row level security, so the policy that refuses to let a session READ
--     another tenant's template does not stop that session POINTING at one.
--
--   COMPOSITE, REFERENCES (tenant_id, template_version_id):
--     the same cross-tenant insert was REJECTED with a foreign key violation, while
--     the same-tenant insert and a NULL template_version_id were both accepted.
--
-- So the single-column form would look like a guard while permitting exactly the
-- cross-tenant write that tenant_deliveries' WITH CHECK asymmetry exists to refuse.
-- Do not weaken this back.
--
-- IT COSTS NO GRANT. The same probe confirmed the writing role needed no SELECT on
-- the referenced table for the check to run, so this constraint does not force a
-- read privilege onto axon_sender and slice 1's "a credential that cannot read
-- cannot be made to leak a ledger" posture is unaffected.
--
-- template_version_id STAYS NULLABLE in this slice. Every existing row is NULL, and
-- email traffic legitimately has no approved template. It becomes NOT NULL for the
-- channels that render through a template on the day an adapter renders one.
--
-- axon.platform_deliveries TAKES NO FOREIGN KEY AT ALL.
-- ck_platform_deliveries_no_template already forces the column NULL there, and that
-- table has no tenant_id to compose a two-column reference from.
--
-- THE GUARD IS A DO BLOCK BECAUSE `ALTER TABLE ... ADD CONSTRAINT IF NOT EXISTS` IS
-- NOT VALID SQL. It was tried: Postgres answers `syntax error at or near "NOT"`.
-- This file has to stay hand-runnable and repeatable, which is 0001's contract for
-- every DDL file in this chain, so the existence check is explicit. The RAISE at the
-- end is not ceremony: a guard whose condition stopped matching would skip the ALTER
-- silently and leave a migration that succeeded with no foreign key.
-- ============================================================================
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_tenant_deliveries_template'
          AND conrelid = 'axon.tenant_deliveries'::regclass
    ) THEN
        ALTER TABLE axon.tenant_deliveries
            ADD CONSTRAINT fk_tenant_deliveries_template
            FOREIGN KEY (tenant_id, template_version_id)
            REFERENCES axon.channel_templates (tenant_id, template_version_id);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fk_tenant_deliveries_template'
          AND conrelid = 'axon.tenant_deliveries'::regclass
    ) THEN
        RAISE EXCEPTION
            'fk_tenant_deliveries_template is still absent after the ADD CONSTRAINT. '
            'The guard above did not match what it was meant to match, and this file '
            'would otherwise have reported success while adding no foreign key.';
    END IF;
END
$$;

COMMENT ON CONSTRAINT fk_tenant_deliveries_template ON axon.tenant_deliveries IS
'Composite on purpose. The single-column form was TESTED and permits one tenant''s delivery to pin another tenant''s template version, because referential-integrity checks bypass row level security. The composite form was tested and rejects it. Do not weaken.';
