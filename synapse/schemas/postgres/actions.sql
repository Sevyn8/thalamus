-- ============================================================================
-- Synapse schema: synapse.actions
--
-- The append-only log of every action Synapse has ever produced. One row per
-- ActionEvent (synapse/src/synapse/core/action.py), written by synapse_writer
-- and read by synapse_reader.
--
-- WRITTEN AGAINST A SHAPE THAT HAS ALREADY RUN. The action types were frozen a
-- slice before this table existed, InMemoryActionLog is a real implementation
-- the unit tests use, and append-only was already enforced by the absence of any
-- mutating method on the protocol. So this DDL describes something exercised,
-- which is the opposite of canonical's signal-history table: a DDL written ahead
-- of its writer, still holding zero rows in both schemas.
--
-- ----------------------------------------------------------------------------
-- WHY THIS IS NOT IN DIS'S ALEMBIC CHAIN
-- ----------------------------------------------------------------------------
-- Synapse is a PEER of DIS, not part of it (D1), and the schema of record is the
-- layer where that has teeth. Under DIS's chain, every Synapse schema change
-- would become a DIS migration, in DIS's runbook, tested by DIS's suite, for a
-- table DIS never reads.
--
-- The usual cost of a second chain is an ordering dependency. IT DOES NOT ARISE
-- HERE, because this table has NO FOREIGN KEYS into any DIS schema — see the
-- deliberate-absence note below. The two chains are independent and may be run
-- in either order. Synapse's chain keeps its own version table
-- (synapse_alembic_version); two chains sharing one database would otherwise
-- both claim public.alembic_version.
--
-- ----------------------------------------------------------------------------
-- NO FOREIGN KEYS, DELIBERATELY
-- ----------------------------------------------------------------------------
-- Not to identity_mirror.tenants, not to canonical.store_sku_current_position,
-- not to anything. AN APPEND-ONLY LOG MUST OUTLIVE EVERYTHING IT REFERENCES: a
-- FK to the tenant mirror would either block mirror-sync from removing a tenant
-- or cascade-delete recorded history, and both destroy the record this table
-- exists to keep.
--
-- Canonical already made this exact call for a weaker version of the same
-- reason: store_sku_sale_events carries no FK to store_sku_current_position,
-- for "lifecycle independence" — sale events outlive positions for delisted
-- SKUs. The argument is stronger for a log whose whole purpose is history.
--
-- ----------------------------------------------------------------------------
-- APPEND-ONLY: WHAT IS ENFORCED, AND WHAT IS NOT
-- ----------------------------------------------------------------------------
-- TWO mechanisms, because they cover different actors:
--
--   1. GRANTS. synapse_writer holds INSERT and nothing else — no UPDATE, no
--      DELETE, no TRUNCATE (infra/db-setup/sql/04_synapse_writer_grant.sql).
--      This stops the application.
--   2. THE TRIGGER below. It raises on UPDATE and DELETE for EVERY role,
--      including the table owner, which a grant can never do. It is what makes
--      an `UPDATE synapse.actions SET ...` typed at a psql prompt fail loudly
--      instead of quietly rewriting history.
--
-- WHAT NEITHER COVERS, stated so nobody reads more into "append-only" than is
-- there:
--
--   - The OWNER can DROP the trigger and then edit. In staging the owner is
--     postgres (cloudsqlsuperuser), so a superuser can always rewrite this log.
--     Nothing in-database prevents that; only backups and PITR make it visible.
--   - DROP TABLE and TRUNCATE by the owner are unaffected by row-level anything.
--   - AND THE IMPORTANT ONE: append-only guarantees that no row was EDITED. It
--     guarantees nothing about whether an appended row was CORRECT. A false
--     action inserted once is permanent. That is the right trade for a log, and
--     it means this table is a faithful record of what the system DID — not a
--     record of what was true. Nobody should read it as trustworthy.
--
-- ----------------------------------------------------------------------------
-- IDEMPOTENCY: uq_actions_idempotency, copying migration 0019 exactly
-- ----------------------------------------------------------------------------
-- Anything that writes here can be retried, and this project has been bitten
-- twice by that: the event sink appended a COMPLETE duplicate set on every
-- Pub/Sub retry (one 328-row upload reached 1640 rows unattended), and the CSV
-- path had no natural key at all.
--
-- THE NATURAL KEY is (declaration_id, declaration_version, verb, as_of, target):
-- the same analysis, at the same revision, asking the same thing, about the same
-- subject, for the same date, is ONE action however many times it is computed.
--
--   verb IS IN THE KEY AS INSURANCE. Verb has one value today, so it changes
--   nothing — but the moment a second verb exists, one subject can legitimately
--   carry two actions, and adding a column to a unique index on a populated
--   table is a migration plus a cleanup. It costs nothing now.
--
--   arm IS DELIBERATELY OUT. It is DERIVED from (salt, subject), so including it
--   would make a deliberate salt change look like a NEW action rather than a
--   changed one — and the salt is explicit precisely so that reshuffling is a
--   decision somebody makes.
--
--   target WORKS AS A KEY COMPONENT BECAUSE IT IS JSONB. Postgres normalises
--   jsonb on storage (sorted keys, no whitespace), so equality is canonical. The
--   same index over `json` or text would be silently defeated by key order.
--
-- THE KEY ALONE IS NOT ENOUGH. Uniqueness on the natural key would
-- suppress a legitimate CORRECTION — a changed quantity, or a changed arm after
-- a salt change — exactly as uniqueness on the canonical dedup key alone would
-- silently drop source corrections. So payload_hash is the final component: a
-- RETRY reproduces the payload byte-for-byte, the hash collides, the insert is
-- suppressed; a CORRECTION differs, so it lands as its own row for `supersedes`
-- to relate.
--
-- ----------------------------------------------------------------------------
-- Dependencies
-- ----------------------------------------------------------------------------
--   - schema: synapse (created by the migration, not by this file)
--   - NOTHING else. No extension, no type, no table in any other schema.
-- ============================================================================


CREATE TABLE synapse.actions (

    -- ---------- Event identity ----------
    event_id                UUID                                NOT NULL,
        -- Supplied by the caller, never minted here or by the application's core
        -- types: uuid4 is banned project-wide, uuidv7 lives in dis_core which
        -- Synapse does not take as a direct dependency, and a pure module that
        -- reads a clock cannot be tested at a boundary.
    recorded_at             TIMESTAMPTZ                         NOT NULL,
        -- When the event was recorded, supplied for the same reason. NOT a
        -- DEFAULT now(): the log records what the caller observed, and a default
        -- would silently substitute the database's clock on a replay.
    supersedes              UUID                                NULL,
        -- The event this one corrects. NO SELF-FK: a correction may legitimately
        -- be written before the row it supersedes is visible to this session, and
        -- an FK would reject it. The relation is advisory and read at analysis
        -- time.

    -- ---------- The target, and its typed projections ----------
    target                  JSONB                               NOT NULL,
        -- The subject of the action, as grain column -> value. THE SINGLE SOURCE
        -- OF TRUTH for the three columns below.

    -- GENERATED, NOT COPIED, and that is the whole point. A CHECK constraint
    -- would DETECT a row whose typed columns disagreed with its target; a
    -- generated column makes the disagreement UNREPRESENTABLE — the column cannot
    -- be inserted into at all ("cannot insert a non-DEFAULT value into column"),
    -- so no write path exists by which a row contradicts itself. Same discipline
    -- as deriving a resolver's column list from the model's field names rather
    -- than typing it out.
    --
    -- STORED (not VIRTUAL) because the value must be indexable and referenceable
    -- from an RLS policy. Both were verified against Postgres before this DDL was
    -- written, including that the policy's WITH CHECK actually EVALUATES the
    -- generated value on INSERT — a cross-tenant insert is refused, which proves
    -- the policy reads the generated column rather than a NULL.
    tenant_id               UUID
        GENERATED ALWAYS AS ((target->>'tenant_id')::uuid) STORED NOT NULL,
        -- NOT NULL, so a target with no tenant_id FAILS THE INSERT. That is
        -- correct: an action nobody can attribute to a tenant cannot be shown to
        -- anyone, and RLS could not scope it.
    store_id                UUID
        GENERATED ALWAYS AS ((target->>'store_id')::uuid) STORED,
    sku_id                  TEXT COLLATE "C"
        GENERATED ALWAYS AS (target->>'sku_id') STORED,
        -- store_id and sku_id NULLABLE on purpose: a future analysis may declare
        -- a different grain, and this table must hold its actions without a
        -- migration. tenant_id is the only projection every action must have.

    -- ---------- The action ----------
    verb                    VARCHAR(32) COLLATE "C"             NOT NULL,
    quantity_at_stake       NUMERIC(14, 3)                      NULL,
        -- UNITS, NOT MONEY, and NULL means UNKNOWN rather than zero. Money would
        -- be stock_qty * unit_cost and is blocked on canonical's own admission
        -- that unit_cost's tax basis is undetermined — the second time that has
        -- blocked money in this plane. Precision matches canonical's stock_qty.
    expires_on              DATE                                NOT NULL,
    arm                     VARCHAR(16) COLLATE "C"             NOT NULL,
        -- treatment | holdout. NO VALUE MEANING "NOT ASSIGNED", and no default:
        -- an action recorded without an arm is permanently outside any study,
        -- because a counterfactual cannot be constructed retrospectively.

    -- ---------- Provenance ----------
    declaration_id          VARCHAR(64) COLLATE "C"             NOT NULL,
    declaration_version     VARCHAR(32) COLLATE "C"             NOT NULL,
    capability_versions     JSONB                               NOT NULL,
        -- capability id -> descriptor version, for every capability the
        -- declaration resolved. An attribution study comparing actions across a
        -- capability version change is averaging two systems.
    thresholds              JSONB                               NOT NULL,
        -- The VALUES used, not a reference to them. A threshold recorded by name
        -- would be re-read later at its new value.
    as_of                   DATE                                NOT NULL,

    -- ---------- Idempotency ----------
    payload_hash            VARCHAR(64) COLLATE "C"             NOT NULL,

    -- ---------- Observations, not scores ----------
    -- The finding's own measure at the moment this action was FIRST recorded. Neither is in
    -- payload_hash's material, so a re-run of the same slot is suppressed and the stored figure
    -- stays the first observation. One per analysis; the other is NULL.
    days_since_last_sale    INTEGER                             NULL,
    days_of_cover           NUMERIC(14, 3)                      NULL,
        -- sha256 hex over the parts of the action that may legitimately differ
        -- between two events sharing a natural key: quantity_at_stake,
        -- expires_on, arm, capability_versions, thresholds. Canonicalised with
        -- sorted keys, the same discipline as the streaming consumer's
        -- canonical_row_hash. See the idempotency note in the header.

    -- ---------- Primary key ----------
    CONSTRAINT pk_actions PRIMARY KEY (event_id),

    -- ---------- Check constraints: the dataclass validators, in the database ----
    -- Each mirrors a __post_init__ check in synapse/src/synapse/core/action.py.
    -- Duplicated deliberately: the type guards the application, these guard
    -- anything that reaches the table by another path.
    CONSTRAINT ck_actions_verb_vocab
        CHECK (verb IN ('review')),

    CONSTRAINT ck_actions_arm_vocab
        CHECK (arm IN ('treatment', 'holdout')),

    CONSTRAINT ck_actions_quantity_non_negative
        CHECK (quantity_at_stake IS NULL OR quantity_at_stake >= 0),

    CONSTRAINT ck_actions_not_expired_on_arrival
        CHECK (expires_on >= as_of),

    CONSTRAINT ck_actions_supersedes_is_not_self
        CHECK (supersedes IS NULL OR supersedes <> event_id),

    CONSTRAINT ck_actions_target_not_empty
        CHECK (jsonb_typeof(target) = 'object' AND target <> '{}'::jsonb),

    CONSTRAINT ck_actions_capability_versions_not_empty
        CHECK (
            jsonb_typeof(capability_versions) = 'object'
            AND capability_versions <> '{}'::jsonb
        ),
        -- Every declaration requires at least one capability, so an empty mapping
        -- means the resolutions were dropped on the way rather than that none
        -- existed.

    CONSTRAINT ck_actions_thresholds_is_object
        CHECK (jsonb_typeof(thresholds) = 'object'),
        -- Empty IS permitted: an analysis with no thresholds is conceivable.

    CONSTRAINT ck_actions_declaration_identified
        CHECK (length(declaration_id) > 0 AND length(declaration_version) > 0)
);


-- ----------------------------------------------------------------------------
-- Idempotency: the natural key plus the payload hash. See the header.
-- ----------------------------------------------------------------------------
CREATE UNIQUE INDEX uq_actions_idempotency
    ON synapse.actions
    (declaration_id, declaration_version, verb, as_of, target, payload_hash);


-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------

-- Every tenant-facing read starts here; RLS filters on this column too.
CREATE INDEX ix_actions_tenant_as_of
    ON synapse.actions (tenant_id, as_of DESC);

-- "What did we do about this SKU" — the attribution question at subject grain.
CREATE INDEX ix_actions_tenant_store_sku
    ON synapse.actions (tenant_id, store_id, sku_id)
    WHERE store_id IS NOT NULL AND sku_id IS NOT NULL;

-- Arm-level rollups for a study, without scanning the whole log.
CREATE INDEX ix_actions_declaration_arm
    ON synapse.actions (declaration_id, declaration_version, arm, as_of);

-- Walking a correction chain backwards.
CREATE INDEX ix_actions_supersedes
    ON synapse.actions (supersedes)
    WHERE supersedes IS NOT NULL;


-- ----------------------------------------------------------------------------
-- Append-only trigger: mechanism 2, the one that binds the owner as well
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION synapse.actions_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'synapse.actions is append-only: % refused. A correction is a NEW row '
        'with its own event_id and supersedes set to the row being corrected.',
        TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_actions_append_only
    BEFORE UPDATE OR DELETE ON synapse.actions
    FOR EACH ROW
    EXECUTE FUNCTION synapse.actions_append_only();


-- ----------------------------------------------------------------------------
-- Row-Level Security
--
-- Same posture as every multi-tenant table in this database: enabled, FORCED,
-- one policy on tenant_id, two-GUC. A multi-tenant table without it would
-- be the exception here, and adding RLS to a populated table is harder than
-- adding it now.
--
-- The policy reads the GENERATED tenant_id. Postgres permits a policy to
-- reference a STORED generated column, and the WITH CHECK genuinely evaluates
-- it — an insert whose target names a different tenant than the session GUC is
-- refused.
-- ----------------------------------------------------------------------------

ALTER TABLE synapse.actions ENABLE ROW LEVEL SECURITY;
ALTER TABLE synapse.actions FORCE ROW LEVEL SECURITY;

CREATE POLICY tenant_isolation
    ON synapse.actions
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

COMMENT ON TABLE synapse.actions IS
'Append-only log of every action Synapse has produced. One row per ActionEvent. No foreign keys into DIS schemas by design: an append-only log must outlive everything it references. Append-only is enforced by grants (synapse_writer has INSERT only) AND by a BEFORE UPDATE OR DELETE trigger that binds every role including the owner. Neither prevents a superuser dropping the trigger, and neither says anything about whether an appended row was CORRECT — this is a faithful record of what the system did, not of what was true.';

COMMENT ON COLUMN synapse.actions.target IS
'The subject of the action, as grain column -> value. The SINGLE SOURCE OF TRUTH for tenant_id / store_id / sku_id, which are GENERATED from it and cannot be written directly.';

COMMENT ON COLUMN synapse.actions.tenant_id IS
'GENERATED ALWAYS from target->>''tenant_id''. Cannot be inserted into, so a row cannot disagree with its own target. NOT NULL, so a target without a tenant_id fails the insert. RLS filters on this column.';

COMMENT ON COLUMN synapse.actions.store_id IS
'GENERATED ALWAYS from target->>''store_id''. NULLABLE: a future analysis may declare a grain without a store.';

COMMENT ON COLUMN synapse.actions.sku_id IS
'GENERATED ALWAYS from target->>''sku_id''. NULLABLE, same reason as store_id.';

COMMENT ON COLUMN synapse.actions.arm IS
'treatment or holdout. Assignment is a deterministic sha256 of (salt, subject), so it is stable across runs and processes without being stored anywhere else and is re-derivable years later. There is no value meaning "not assigned": an action recorded without an arm is permanently outside any study.';

COMMENT ON COLUMN synapse.actions.quantity_at_stake IS
'Units of inventory at stake. NULL means UNKNOWN (canonical''s stock_qty is nullable), never zero — zero would sort a dead position to the bottom of any list built on this. Not money: unit_cost''s tax basis is undetermined by canonical''s own column comment.';

COMMENT ON COLUMN synapse.actions.payload_hash IS
'sha256 hex over the parts of an action that may legitimately differ between two events sharing a natural key. The fifth component of uq_actions_idempotency, and what lets that index suppress a RETRY (identical payload, hash collides) while letting a CORRECTION land as its own row. Copies migration 0019''s resolution of the same problem in canonical.';

COMMENT ON COLUMN synapse.actions.days_since_last_sale IS
'Observation, not a score: the dead_stock finding''s own measure at the moment the action was
first recorded. NULL means the row predates this migration, or the input was unavailable for
this analysis (stockout_risk never sets it). Outside payload_hash by construction.';

COMMENT ON COLUMN synapse.actions.days_of_cover IS
'Observation, not a score: the stockout_risk finding''s own measure at first recording. NULL
means the row predates this migration, or the analysis does not produce it (dead_stock).';

COMMENT ON COLUMN synapse.actions.supersedes IS
'The event this one corrects, or NULL. Deliberately NOT a foreign key to event_id: a correction may be written before the row it supersedes is visible to the session, and an FK would reject it.';
