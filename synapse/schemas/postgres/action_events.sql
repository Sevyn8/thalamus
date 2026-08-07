-- ============================================================================
-- synapse.action_events — what an operator did about an alert
-- ============================================================================
--
-- THE FIRST OPERATOR WRITE PATH IN SYNAPSE. Everything before it was produced by
-- the orchestrator; this is the one table a human causes rows in, from the
-- superadmin console.
--
-- WHY A SEPARATE TABLE AND NOT COLUMNS ON synapse.actions. Two reasons, and the
-- second is structural. First, D1: nothing sits between propose and record, and a
-- mutable `status` column on the action log would put a human decision inside the
-- attribution denominator. Second, synapse.actions is append-only by a trigger that
-- binds even the table owner — a column you cannot UPDATE is not a state column, so
-- the alternative was never actually available.
--
-- APPEND-ONLY, THE SAME TWO MECHANISMS AS synapse.actions. A dismissal is a fact
-- about what somebody decided at a moment; changing your mind is a NEW event, not an
-- edited one. The audit value of a lifecycle log is exactly the part an UPDATE
-- destroys.
--
-- CLOSED VOCABULARIES, NOT FREE TEXT. `reason` doubles as a false-positive training
-- label, so it has to be a value something can GROUP BY in a year's time. There is
-- deliberately no note column: a note is the crack through which a training label
-- becomes prose, and prose cannot be counted.
--
-- ---------------------------------------------------------------------------
-- THE TARGET GRAIN IS RECORDED ON THE EVENT, and this is the load-bearing decision
-- ---------------------------------------------------------------------------
-- An operator who snoozes an alert means "stop showing me THIS PRODUCT AT THIS STORE
-- for 30 days". They do not mean "stop showing me the row with this event_id" —
-- tomorrow's detection is a NEW row with a new event_id, so a per-event snooze would
-- evaporate on precisely the alert it was meant to silence.
--
-- So the event carries BOTH:
--
--   action_event_id  the alert the operator actually clicked. Provenance: what was
--                    on screen when they decided. Never used for matching.
--   declaration_id   the grain the decision APPLIES to, copied from that alert at
--   target           write time. (declaration_id, target) is the same key the
--                    actions idempotency index uses, so "the same alert tomorrow"
--                    and "the same alert for lifecycle" cannot drift apart.
--
-- Denormalised rather than joined because the writing role holds INSERT and nothing
-- else — see the grants in migration 0006. The values are copied by the caller,
-- which reads the alert through the READER credential first.
--
-- ---------------------------------------------------------------------------
-- THIS TABLE NEVER SUPPRESSES A DETECTION (D1)
-- ---------------------------------------------------------------------------
-- The orchestrator does not read it. A snoozed target keeps producing rows in
-- synapse.actions every slot it is detected, and the snooze is applied at READ TIME
-- by the console's queries. When the snooze expires the full history is there,
-- including everything detected while it was quiet — which is the point: a snooze
-- hides a row from a screen, it does not un-observe the world.
--
-- ---------------------------------------------------------------------------
-- NO FOREIGN KEY TO synapse.actions
-- ---------------------------------------------------------------------------
-- That table has none into any DIS schema, for the stated reason that an append-only
-- log must outlive what it references. A lifecycle event should not be stricter than
-- the thing it annotates.

CREATE TABLE IF NOT EXISTS synapse.action_events (

    -- UUIDv7, supplied by the caller. Same discipline as ActionEvent.event_id:
    -- uuid4 is banned project-wide and the clock-reading layer mints the id.
    lifecycle_event_id  UUID                                NOT NULL,

    -- PROVENANCE, not a matching key. The alert that was on screen.
    action_event_id     UUID                                NOT NULL,

    -- RLS scope. Denormalised like everything else here; no FK.
    tenant_id           UUID                                NOT NULL,

    -- THE GRAIN THE DECISION APPLIES TO. See the header.
    declaration_id      VARCHAR(64) COLLATE "C"             NOT NULL,
    target              JSONB                               NOT NULL,

    -- ---------- The decision ----------
    -- Closed set, enforced by CHECK rather than by an enum type: the same choice
    -- ck_run_outcome made, and it keeps adding a verb a migration rather than a
    -- type alteration with a table rewrite behind it.
    verb                VARCHAR(16) COLLATE "C"             NOT NULL,

    -- Dismiss only, and required there. These four are the false-positive training
    -- labels; a dismissal without one is an unlabelled negative example, which is
    -- the whole value of asking.
    reason              VARCHAR(32) COLLATE "C"             NULL,

    -- Snooze only, and required there. A DATE, not a timestamp: an operator picks
    -- days, and the read-time comparison is against the slot date.
    snoozed_until       DATE                                NULL,

    -- ---------- Who and when ----------
    -- THE AUTH0 SUBJECT, AND THAT IS ALL THE SESSION HONESTLY CARRIES. Identity has
    -- subject / user_type / tenant_id and no email or name — Customer Master's Auth0
    -- Action stamps no name claim, which is a standing ledger item. Storing a
    -- display name here would mean inventing one.
    actor_subject       TEXT                                NOT NULL,

    -- Supplied by the caller, never DEFAULT now(): the log records what the caller
    -- observed, and a default would substitute the database's clock on a replay.
    recorded_at         TIMESTAMPTZ                         NOT NULL,

    CONSTRAINT pk_action_events PRIMARY KEY (lifecycle_event_id),

    CONSTRAINT ck_action_events_verb
        CHECK (verb IN ('snooze', 'dismiss', 'acknowledge')),

    -- A reason is required for dismiss and forbidden elsewhere. Both directions:
    -- an unlabelled dismissal loses the training signal, and a reason on an
    -- acknowledge would be a label nobody asked for sitting in the same column.
    -- CASE, NOT `AND ... IN (...)`, AND THREE-VALUED LOGIC IS WHY. The first version read
    --     (verb = 'dismiss' AND reason IN (...)) OR (verb <> 'dismiss' AND reason IS NULL)
    -- which ACCEPTS a dismissal with a NULL reason: `NULL IN (...)` is NULL, `true AND NULL`
    -- is NULL, `NULL OR false` is NULL, and a CHECK passes when it evaluates to NULL. So the
    -- one combination the column exists to prevent — an unlabelled dismissal — was legal.
    -- Found by executing the migration against a real table, not by reading it.
    CONSTRAINT ck_action_events_reason
        CHECK (
            CASE WHEN verb = 'dismiss'
                 THEN reason IS NOT NULL
                      AND reason IN ('seasonal', 'display_stock', 'discontinued', 'wrong_data')
                 ELSE reason IS NULL
            END
        ),

    -- Likewise for the date. A snooze with no expiry is a dismissal wearing the
    -- wrong verb, and it would never resurface.
    -- Written as a CASE for the same reason, though this one is already NULL-safe: IS NULL and
    -- IS NOT NULL never yield NULL. Matched to its sibling so the pair reads as one rule.
    CONSTRAINT ck_action_events_snooze
        CHECK (
            CASE WHEN verb = 'snooze'
                 THEN snoozed_until IS NOT NULL
                 ELSE snoozed_until IS NULL
            END
        )
);

-- The read pattern is "latest event for this target", so the index leads with the
-- grain and orders by time. Covers both the per-target resolution and the detail
-- page's per-alert event log.
CREATE INDEX IF NOT EXISTS ix_action_events_target
    ON synapse.action_events (tenant_id, declaration_id, target, recorded_at DESC);

CREATE INDEX IF NOT EXISTS ix_action_events_alert
    ON synapse.action_events (action_event_id, recorded_at DESC);

COMMENT ON TABLE synapse.action_events IS
'What an operator did about an alert: snooze, dismiss (with a closed reason set that doubles as a false-positive training label) or acknowledge. Append-only, like synapse.actions. NEVER read by the orchestrator: a snooze hides rows at READ time and never suppresses a detection, so the full history including the snoozed period is visible once it expires.';

COMMENT ON COLUMN synapse.action_events.action_event_id IS
'The alert the operator clicked. PROVENANCE ONLY — matching is by (declaration_id, target), because a snooze means "this product at this store", and tomorrow''s detection of the same thing is a different event_id.';

COMMENT ON COLUMN synapse.action_events.target IS
'The grain the decision applies to, copied from the alert at write time. Same key the actions idempotency index uses, so lifecycle and detection cannot disagree about what "the same alert" is.';

COMMENT ON COLUMN synapse.action_events.actor_subject IS
'The Auth0 `sub` of the operator. The only identity the console session carries: there is no name or email claim, so no display name is stored or storable.';


-- ----------------------------------------------------------------------------
-- Append-only: the trigger that binds the owner too
-- ----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION synapse.action_events_append_only()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION
        'synapse.action_events is append-only: % refused. Changing a decision is a '
        'NEW event with its own lifecycle_event_id.',
        TG_OP
        USING ERRCODE = 'restrict_violation';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_action_events_append_only ON synapse.action_events;
CREATE TRIGGER trg_action_events_append_only
    BEFORE UPDATE OR DELETE ON synapse.action_events
    FOR EACH ROW
    EXECUTE FUNCTION synapse.action_events_append_only();


-- ----------------------------------------------------------------------------
-- Row-Level Security: the same two-GUC policy as synapse.actions
-- ----------------------------------------------------------------------------
-- PLATFORM widens READS only. WITH CHECK compares app.tenant_id, so the console's
-- write must open a TENANT-scoped session for the alert's tenant — a PLATFORM
-- session (tenant GUC '') can read every event and write none.
ALTER TABLE synapse.action_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE synapse.action_events FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON synapse.action_events;
CREATE POLICY tenant_isolation
    ON synapse.action_events
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        OR current_setting('app.user_type', true) = 'PLATFORM'
    )
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
