-- ============================================================================
-- synapse.run — one row per (tenant, analysis, slot). The DENOMINATOR.
--
-- WHY THIS EXISTS WHEN synapse.actions ALREADY DEDUPLICATES. The actions index
-- (declaration_id, declaration_version, verb, as_of, target, payload_hash) already
-- suppresses a re-run that produces identical actions, and that is sufficient for
-- CORRECTNESS. It is not sufficient for OBSERVABILITY, for one specific reason:
--
--   A RUN THAT PRODUCED ZERO ACTIONS IS INDISTINGUISHABLE FROM A RUN THAT NEVER
--   HAPPENED. Absence cannot be read from a table of presences.
--
-- That is dead_stock's own argument one layer up — the analysis exists because a
-- SKU that never sold produces no rows in a table of sales — and for dead_stock the
-- zero-action run is LIKELY rather than hypothetical: the declaration's own
-- stands_in_for text notes that one dead SKU against a 20% holdout has roughly a
-- one-in-five chance of yielding zero treated actions.
--
-- And the denominator is the deciding half. "How many tenant-days did we observe"
-- cannot be computed from the numerator, and like the holdout arm it cannot be
-- retrofitted: a day nobody recorded is a day that did not happen as far as any
-- later study can tell.
--
-- ----------------------------------------------------------------------------
-- THE SLOT KEY, AND WHY IT IS UNIQUE
-- ----------------------------------------------------------------------------
-- uq_run_slot on (tenant_id, analysis_id, slot). The slot is derived inside the
-- process by synapse.core.slot.slot_for, floored to the cadence in the tenant's
-- reporting timezone — NOT read from the dispatch, because a dispatch cannot carry
-- it: Cloud Scheduler sets X-CloudScheduler-ScheduleTime only on HTTP targets, and a
-- Cloud Run JOB is launched through the Run Admin API with static args and receives
-- no headers at all.
--
-- The uniqueness is what makes a redelivered dispatch the SAME run rather than a
-- second one. This matters more than it looks: setting max_retries = 0 on the job
-- does NOT stop retries, because Cloud Scheduler retries its own API call, so a
-- second execution can be launched whatever the job's retry policy says.
--
-- ----------------------------------------------------------------------------
-- THIS TABLE IS NOT APPEND-ONLY, AND THAT IS A DELIBERATE DIFFERENCE
-- ----------------------------------------------------------------------------
-- synapse.actions is immutable because it records what the system DID; an edited
-- action destroys the history a study is built on. A run row records the STATE OF AN
-- ATTEMPT, which by definition changes: it is claimed, then it finishes. So there is
-- no append-only trigger here, and its absence is a decision rather than an
-- oversight.
--
-- The crash-recovery consequence is the reason the state machine is what it is. A
-- claimed-but-unfinished row means a previous attempt died mid-run: outcome IS NULL
-- is the marker, and a later attempt TAKES IT OVER and completes it rather than
-- skipping. Skipping would leave a partially-appended slot permanently incomplete,
-- and re-running is safe because the actions index absorbs everything already
-- written. A row with a terminal outcome is skipped.
-- ============================================================================


CREATE TABLE IF NOT EXISTS synapse.run (
    -- UUIDv7 minted by the orchestrator (dis_core.ids.new_uuid7). synapse.core mints
    -- nothing — uuid4 is banned project-wide and a pure module must not read a clock —
    -- so ids arrive from the layer that is allowed to have both.
    run_id              UUID                        NOT NULL,

    tenant_id           UUID                        NOT NULL,
    analysis_id         TEXT COLLATE "C"            NOT NULL,

    -- The scheduled occurrence this attempt belongs to. DATE because the only cadence
    -- is daily and because it is the same grain as actions.as_of, which it feeds.
    slot                DATE                        NOT NULL,

    -- WHAT WAS IN FORCE WHEN THIS RAN, snapshotted rather than joined. The provision
    -- row is mutable: an operator changing a tenant's timezone or rung next month must
    -- not silently rewrite what last month's runs are recorded as having done. Same
    -- reason Provenance is copied onto an action rather than referenced.
    cadence             TEXT COLLATE "C"            NOT NULL,
    rung                TEXT COLLATE "C"            NOT NULL,
    timezone            TEXT COLLATE "C"            NOT NULL,

    started_at          TIMESTAMPTZ                 NOT NULL,
    -- NULL until the attempt terminates. With outcome, this is the claimed/finished
    -- distinction the crash-recovery path reads.
    finished_at         TIMESTAMPTZ                 NULL,

    -- NULL means CLAIMED AND UNFINISHED — either running now or died mid-run. A later
    -- attempt takes such a row over. Terminal values are skipped.
    outcome             TEXT COLLATE "C"            NULL,

    -- What the run produced. proposed and appended DIFFER when the actions index
    -- suppresses a repeat, and keeping both is what makes a re-run legible: a second
    -- attempt at the same slot proposing 4 and appending 0 is the idempotency working,
    -- not a failure.
    actions_proposed    INTEGER                     NULL,
    actions_appended    INTEGER                     NULL,

    -- Why a run was blocked or how it failed. Free text: it carries a resolution
    -- outcome's own explanation, which is prose by design.
    detail              TEXT                        NULL,

    -- WHAT THE ANALYSIS COULD NOT ASSESS, as {reason: count} over a CLOSED vocabulary
    -- (synapse.core.stockout_risk.RefusalReason). Added by migration 0005.
    --
    -- THE COLUMN THAT DISTINGUISHES TWO ZEROES. actions_proposed = 0 means either
    -- "looked and found nothing" or "could not look" — and until this existed nothing
    -- in the data told them apart, so the console rendered a third state meaning
    -- "zero, and we cannot tell which". A run that refused every series as stale now
    -- says so here.
    --
    -- NULL vs '{}' IS MEANINGFUL AND NOT AN ACCIDENT. NULL = the run never reached its
    -- plan (blocked, undeclared, failed, or predating this migration), so nothing was
    -- assessable to begin with. '{}' = the plan RAN and refused nothing. Rendering the
    -- two the same way would report a crashed run as a clean one.
    --
    -- JSONB rather than five typed columns: the vocabulary grows with the analyses, and
    -- a column per reason would make every new refusal branch a migration. Rather than a
    -- child table because this is one small map read only alongside its run row, never
    -- joined or aggregated across runs.
    --
    -- KEYS ARE WRITTEN SORTED (run_postgres.complete). synapse.run is NOT append-only --
    -- see below -- so a re-run may rewrite this row, and the correctness rule is that
    -- the same slot over the same data yields the same bytes. Python dicts preserve
    -- insertion order, which follows refusal order, so sorting is what makes that true.
    refusals            JSONB                       NULL,

    CONSTRAINT pk_run PRIMARY KEY (run_id),

    -- THE SLOT KEY. One run per tenant per analysis per slot, forever.
    CONSTRAINT uq_run_slot UNIQUE (tenant_id, analysis_id, slot),

    CONSTRAINT ck_run_analysis_named
        CHECK (length(analysis_id) > 0),

    CONSTRAINT ck_run_cadence
        CHECK (cadence IN ('daily')),
    CONSTRAINT ck_run_rung
        CHECK (rung IN ('shadow', 'suggest')),
    CONSTRAINT ck_run_timezone_present
        CHECK (length(timezone) > 0),

    -- The terminal vocabulary. 'satisfied' means the declaration resolved and the
    -- analysis ran; 'blocked' and 'undeclared' are the other two DeclarationResolution
    -- outcomes, kept distinct because they mean different things to an operator; and
    -- 'failed' is an exception during the run.
    CONSTRAINT ck_run_outcome
        CHECK (outcome IS NULL OR outcome IN ('satisfied', 'blocked', 'undeclared', 'failed')),

    -- Finished and terminal travel together, in both directions. A finished row with
    -- no outcome, or an outcome with no finish, is a state the state machine cannot
    -- produce and should not be storable.
    CONSTRAINT ck_run_finished_iff_outcome
        CHECK ((finished_at IS NULL) = (outcome IS NULL)),

    -- Counts belong to a run that got far enough to produce them, and cannot be
    -- negative. Both NULL is the unfinished case and the blocked case alike.
    CONSTRAINT ck_run_counts_nonnegative
        CHECK (
            (actions_proposed IS NULL OR actions_proposed >= 0)
            AND (actions_appended IS NULL OR actions_appended >= 0)
        ),
    -- Appended can never EXCEED proposed: the index suppresses, it never invents.
    CONSTRAINT ck_run_appended_within_proposed
        CHECK (
            actions_proposed IS NULL
            OR actions_appended IS NULL
            OR actions_appended <= actions_proposed
        ),

    CONSTRAINT ck_run_finished_after_started
        CHECK (finished_at IS NULL OR finished_at >= started_at)
);


-- ----------------------------------------------------------------------------
-- Indexes
-- ----------------------------------------------------------------------------

-- "What ran, and how did it go" for one tenant, newest first. The operator query.
CREATE INDEX IF NOT EXISTS ix_run_tenant_slot
    ON synapse.run (tenant_id, slot DESC);

-- Unfinished runs across all tenants: the crash-recovery and monitoring sweep.
-- Partial, because in a healthy system this matches almost nothing.
CREATE INDEX IF NOT EXISTS ix_run_unfinished
    ON synapse.run (started_at)
    WHERE outcome IS NULL;


-- ----------------------------------------------------------------------------
-- RLS: the same two-GUC policy. Read as PLATFORM by the orchestrator's sweep,
-- per-tenant by anything showing an operator one tenant's history.
--
-- WITH CHECK pins writes to the acted-for tenant, so a PLATFORM no-tenant session
-- can enumerate every run and write none — which is what the enumeration pass wants.
-- The orchestrator therefore claims and completes a run under TENANT scope for the
-- tenant it is acting for, not under the enumerating session.
-- ----------------------------------------------------------------------------
ALTER TABLE synapse.run ENABLE ROW LEVEL SECURITY;
ALTER TABLE synapse.run FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON synapse.run;
CREATE POLICY tenant_isolation
    ON synapse.run
    AS PERMISSIVE
    FOR ALL
    TO PUBLIC
    USING (
        tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
        OR current_setting('app.user_type', true) = 'PLATFORM'
    )
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);


COMMENT ON TABLE synapse.run IS
'One row per (tenant, analysis, slot). The attribution DENOMINATOR: a zero-action run is invisible in synapse.actions, because absence cannot be read from a table of presences. NOT append-only, unlike synapse.actions — a run row records the state of an attempt, which changes.';
COMMENT ON COLUMN synapse.run.slot IS
'The scheduled occurrence, floored to the cadence in the tenant''s reporting timezone by synapse.core.slot.slot_for. Derived in-process because a Cloud Run job receives no scheduled time: X-CloudScheduler-ScheduleTime is an HTTP-target header and a job is launched through the Run Admin API.';
COMMENT ON COLUMN synapse.run.outcome IS
'NULL means claimed and unfinished — running now, or died mid-run and awaiting takeover by a later attempt. Terminal values are skipped on a repeat dispatch.';
COMMENT ON COLUMN synapse.run.actions_appended IS
'Appended may be less than proposed: the actions idempotency index suppresses a repeat. A second attempt proposing N and appending 0 is the idempotency working.';
