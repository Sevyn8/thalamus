-- ============================================================================
-- synapse.quarantined_tenants + synapse.actions_analytical
-- ============================================================================
--
-- WHY THIS EXISTS. Thirteen rows in synapse.actions are test fixtures written by
-- live tests before the suite was isolated. They are IMMORTAL: the append-only
-- trigger refuses DELETE for every role including the owner, so removing them is
-- not an option that exists. Growth is already stopped. What was left was the
-- risk that a future weight-fitting or attribution job scans the table and
-- trains on fiction without anyone noticing — a silent failure, because thirteen
-- plausible-looking rows do not announce themselves.
--
-- So the rows stay and the ANALYTICS SURFACE CHANGES. synapse.actions_analytical
-- is the table minus every registered tenant, and it is the surface analytical
-- work should read.
--
-- ---------------------------------------------------------------------------
-- A REGISTRY FOR ONE ROW, AND THE REASON IS NOT "WE MIGHT ADD MORE"
-- ---------------------------------------------------------------------------
-- One sentinel does not justify a table on YAGNI grounds, and a bare
-- `WHERE tenant_id <> '...'` in the view would have been simpler. The registry
-- earns its place because it is where the PROVENANCE lives, and the provenance
-- is the part that stops the next person getting this wrong.
--
-- decafbad is not merely an id to exclude. It is a REAL PROVISIONED TENANT with
-- real orchestrator behaviour: it has runs, and its freshness WARNINGs exercise
-- the alert emission path. Its ACTIONS are fixture writes; its RUNS
-- are genuine executions worth watching. A predicate records the exclusion and
-- says nothing about that asymmetry, so the next person asking "should the
-- freshness alerting exclude it too?" gets no answer. The `note` column answers
-- it.
--
-- Second, weaker reason: a registry is JOINABLE. Any future query can ask "is
-- this tenant real?" without importing a literal from somewhere.
--
-- ---------------------------------------------------------------------------
-- SCOPE IS ACTIONS ONLY, DELIBERATELY
-- ---------------------------------------------------------------------------
-- synapse.run and the freshness path are NOT filtered. Quarantining them would
-- hide working machinery and suppress the very signal that shows the alert
-- pipeline working. The asymmetry is principled rather than lazy.
--
-- IF RUN DATA EVER BECOMES A MODEL INPUT — "how often does this analysis produce
-- actions" is a natural weight-fitting denominator — the same exposure appears
-- for synapse.run and the scope should be revisited CONSCIOUSLY. It is recorded
-- here so that revisit is a decision rather than a discovery.
--
-- ---------------------------------------------------------------------------
-- THE REGISTRY IS NOT APPEND-ONLY, AND THAT IS THE POINT
-- ---------------------------------------------------------------------------
-- Unlike synapse.actions, this table can be corrected. A wrong entry excludes a
-- real tenant from analytics, which is bad and CHEAPLY REVERSIBLE — one DELETE.
-- An append-only registry would make a typo permanent, which is the failure mode
-- of the thing it is trying to contain.
--
-- No application role holds INSERT. Seeding is a migration's job, running as the
-- schema owner: a quarantine list the application can edit is not a quarantine.

CREATE TABLE IF NOT EXISTS synapse.quarantined_tenants (

    -- The tenant whose ACTIONS are excluded from analytical reads.
    tenant_id       UUID                                NOT NULL,

    -- Closed set, enforced by CHECK rather than an enum type — the same choice
    -- ck_run_outcome and ck_action_events_verb made, and it keeps adding a
    -- category a migration rather than a type alteration.
    reason          VARCHAR(32) COLLATE "C"             NOT NULL,

    -- REQUIRED, and required is the whole design. An entry without provenance is
    -- an id somebody will one day be afraid to remove because nothing says what
    -- it was for. Free text HERE is correct where it is wrong on action_events:
    -- nothing counts this column, a human reads it.
    note            TEXT                                NOT NULL,

    registered_at   TIMESTAMPTZ                         NOT NULL,

    -- Who decided. A migration revision for a seeded row, an operator for a
    -- hand-added one. Not an FK to anything: this outlives whatever it names.
    registered_by   TEXT                                NOT NULL,

    CONSTRAINT pk_quarantined_tenants PRIMARY KEY (tenant_id),

    CONSTRAINT ck_quarantined_tenants_reason
        CHECK (reason IN ('test_fixture')),

    -- A blank note passes NOT NULL and defeats the column's purpose.
    CONSTRAINT ck_quarantined_tenants_note_is_real
        CHECK (length(btrim(note)) >= 40)
);

COMMENT ON TABLE synapse.quarantined_tenants IS
'Tenants whose rows in synapse.actions are fixtures rather than findings. Read by synapse.actions_analytical, which is the surface analytical work should use. Scope is ACTIONS ONLY: a quarantined tenant''s runs and freshness signals stay visible because they are real orchestrator behaviour. Correctable by design (one DELETE) — unlike synapse.actions, which is append-only.';

COMMENT ON COLUMN synapse.quarantined_tenants.note IS
'Why this tenant is quarantined and what about it is still real. Required and length-checked: an entry without provenance becomes an id nobody dares remove.';


-- ----------------------------------------------------------------------------
-- The analytical surface
-- ----------------------------------------------------------------------------
-- NAMED FOR ITS PURPOSE, not its mechanism. `actions_analytical` tells a reader
-- WHEN to use it — which is the decision they are actually making — where
-- `actions_excluding_quarantined` describes the implementation and invites
-- "excluding what, and do I care?". The purpose name also survives a change to
-- the exclusion rule; the mechanism name would need renaming and would then lie
-- in every query already written against it.
--
-- security_invoker = true IS LOAD-BEARING. synapse.actions is FORCE ROW LEVEL
-- SECURITY. A view executes with its OWNER's rights by default, so an ordinary
-- view over an RLS table is a cross-tenant read hole — the exact opposite of
-- what this object is for. security_invoker makes the querying role's policies
-- apply. DIS's config.source_mappings_v carries the same guard for the same
-- reason.
--
-- NOT EXISTS rather than a LEFT JOIN with an IS NULL: one row per action either
-- way, and the anti-join cannot accidentally duplicate a row if the registry
-- ever gains a second key column.
CREATE OR REPLACE VIEW synapse.actions_analytical
    WITH (security_invoker = true) AS
SELECT a.*
  FROM synapse.actions a
 WHERE NOT EXISTS (
     SELECT 1 FROM synapse.quarantined_tenants q
      WHERE q.tenant_id = a.tenant_id
 );

COMMENT ON VIEW synapse.actions_analytical IS
'synapse.actions minus every tenant listed in synapse.quarantined_tenants. USE THIS FOR ANALYTICS — weight fitting, attribution, any model input. The base table retains immortal test-fixture rows (append-only; deletion is impossible by design) which are real-looking and would train a model on fiction. Scope is actions only: quarantined tenants keep their runs and freshness signals, which are genuine. security_invoker: executes with the querying role''s rights so synapse.actions'' FORCE RLS still applies.';
