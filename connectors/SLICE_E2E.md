# Slice: thin end-to-end Square snapshot (offline)

Status: PLAN for review. No implementation code until approved.

## Objective

Prove one vertical slice end to end: onboard a seeded tenant through a ver2 screen,
provision an api-source plus a Square snapshot template via the EXISTING BFF endpoints,
run ONE offline Square pull through a manual trigger transport, land rows in
`canonical.store_sku_current_position` through the inherited pipeline, and see the
connector on `GET /connector-health`.

Backend spine first (seed to provision to trigger to pull to canonical, verifiable by
test and CLI), then the ver2 screen on top.

## Scope guardrails

Do NOT touch streaming-consumer, mapping, validation, canonical, or any frozen Pub/Sub
contract. Do NOT build scheduling, real Square OAuth, or the RS256/JWKS auth swap. Do NOT
fix the config.py Square base-url naming (separate follow-up). Offline-first: the pull
runs against a FAKE SquareApi returning canned catalog plus inventory JSON, no network.

## Grounding facts (verified against the tree)

- `ConnectorTrigger` (sdk/trigger.py) carries `trace_id`, `connector_run_id`, `tenant_id`,
  `store_id`, `source_id`, `template_id`, `domains`, optional `cursor`. The receiver reads
  all of them and mints none; `connector_run_id` is the dedup `source_payload_id` and its
  minting authority is the trigger PRODUCER (the transport).
- `thalamus_square/main.py` exposes `run_trigger(pipeline, trigger)` as the seam the
  transport calls. The transport itself is explicitly out of scope for the receiver, so it
  is THIS slice's core new backend artifact.
- `build_square_pipeline(sdk_config, square_config, *, engine, token_store=None, api=None)`
  already accepts an injected `token_store` and `api`, so the offline pull needs no change
  to the receiver: the transport passes a fake `SquareApi` and a fake `TokenStore`.
- `SquareApi` Protocol (puller.py): `list_locations`, `list_catalog -> CatalogPage`,
  `batch_inventory -> dict`, `search_orders -> OrdersPage`. The snapshot pull uses
  `domains=[CATALOG]`, which drives `list_locations` (authenticate), `list_catalog`, and
  `batch_inventory`. The fake supplies canned data for those three; `search_orders` returns
  empty.
- Snapshot completeness requires only `{sku_id, product_name, current_retail_price}` from
  the mapping (proven earlier); `currency` and `tax_treatment` are enrichment-produced from
  `identity_mirror.stores`. So the seeded store MUST carry `currency` and `tax_treatment`.
- CORRECTION to the task note: `make seed` (dis-testing `seed.py`) writes ONLY
  `config.source_mappings` and fail-loud requires the tenant already mirrored. The
  `identity_mirror` tenant plus store rows (with `currency` and `tax_treatment`) are loaded
  by MIRROR-SYNC via `make run-local: sync` (Makefile line 24), from the Customer Master
  stand-in. Store fixtures carry the values (for example `USD` / `EXCLUSIVE`,
  `PLN` / `INCLUSIVE`). So the real Step 1 prerequisite is `make run-local` (which runs
  `sync`), not the seeder. The seeder's default csv mapping is unused by this slice, which
  provisions its own source and template via the BFF.
- BFF endpoints exist and are REUSED as-is:
  - `POST /sources` (handlers/sources.py): `SourceCreate` with `source_id`, `display_name`,
    `channel`, optional `store_id`, `schedule`, `acting_for_tenant_id`. Auth via
    `require_write_scope` plus `resolve_acted_for`. Set `channel="api"`.
  - `POST /mapping-templates` (handlers/mapping_templates.py): `MappingTemplateCreate` with
    `template_type`, `source_id`, `template_name`, per-column semantic intent
    (`src_key -> dest_key` plus source-format declarations), optional `acting_for_tenant_id`.
    It translates to `mapping_rules`, validates, and writes one ACTIVE row. Use
    `template_type="snapshot"`; the returned detail carries the `template_id`.
  - `GET /connector-health` (handlers/connector_health.py): drives from `config.sources`,
    LEFT JOINs `telemetry.connector_health` and the bronze last-arrival, derives status.
- ver2 auth-viability (verified, correcting the earlier draft): a dev-auth mode EXISTS on
  BOTH sides and already honors the full claim contract.
  - BFF: `dis_ui_server/auth/verifier.py` is the HS256 DEV-STUB verifier, the single seam
    the later CM JWKS swap replaces. It REQUIRES `exp`, `iss`, `aud`, `sub`, and `user_type`
    (`TENANT`|`PLATFORM`, reject-on-ambiguous) and enforces user_type<->tenant_id coherence.
    Constants: secret `dis-ui-dev-stub-secret-not-for-production`, `iss
    https://customer-master.local`, `aud dis`.
  - ver2: `auth/dev/signStubToken.ts` (jose `SignJWT`, HS256) mints
    `sub`/`tenant_id`/`store_id`/`user_type`/`roles` + `iss`/`aud`/`exp`, from
    `auth/dev/devStubSecret.ts` whose `STUB_SECRET`/`STUB_ISSUER`/`STUB_AUDIENCE` are
    byte-identical to the BFF. `/dev/login` (DevLogin) + `AuthBoundary` + `verifyToken.ts`
    are in place; `verifyToken.ts` is the documented seam for the later JWKS swap.
  So the `user_type` claim is ALREADY present and the dev token round-trips through the BFF
  verifier. The earlier "dev token missing user_type" note was wrong. The two REAL ver2
  gaps are: (1) `vite.config.ts` proxies `/api` to `... || 'http://localhost:8081'` (should
  be the BFF on 8080); (2) the dev personas (`auth/dev/personas.ts`) carry STALE placeholder
  `tenant_id`/`store_id` in the retired `t_*`/`s_*` form, not the seeded internal UUIDs.
  `scope.py` `tenant_uuid_of` does `UUID(identity.tenant_id)` and rejects a non-UUID (401),
  and RLS/FK need the value to equal the seeded tenant, so the slice needs a dev persona
  carrying the seeded buc-ees UUIDs.

## Trigger-transport design (the core new artifact)

A manual CLI (the PRODUCER role). It:

1. Reads the run identity as CLI args resolved from the seeded plus provisioned rows:
   `--tenant-id`, `--store-id`, `--source-id`, `--template-id`, and a REQUIRED `--run-key`.
   `--run-key` is the PRODUCER-declared logical-run boundary. It has NO default: a fixed
   default sentinel would over-dedup every future snapshot of the source to one id forever
   (violates distinctness), and a `now()` default would make every retry a new id (violates
   retry-stability). So the producer must name the run explicitly.
2. Mints `connector_run_id` DETERMINISTICALLY from the producer-supplied `run_key` (mirrors
   dis-ui-server's `us_` derivation). Exact function:
   ```python
   import hashlib
   def mint_connector_run_id(tenant_id, store_id, source_id, template_id, run_key):
       # ids stringified as canonical lowercase UUIDs; run_key is the caller-supplied
       # logical-run boundary (NEVER now(), NEVER a fixed source-only sentinel).
       material = f"{tenant_id}|{store_id}|{source_id}|{template_id}|{run_key}"
       return "run_" + hashlib.sha256(material.encode()).hexdigest()[:12]
   ```
   Same-logical-run vs new-run, stated precisely: two invocations are the SAME logical run iff
   they carry the same `(tenant_id, store_id, source_id, template_id, run_key)`. A RETRY of a
   run re-invokes with the SAME `run_key` (same id, so the 24h dedup collapses it). A new
   INTENDED pull (a legitimate later refresh) uses a NEW `run_key` (a new id, NOT deduped
   away), for example the operator names the bootstrap `bootstrap-001` and a later refresh
   `refresh-001`. The names are operator-chosen strings, not derived from wall-clock in code;
   the derivation contains no `now()`. Length is 16 (`run_` + 12 hex), satisfying
   `ConnectorTrigger.connector_run_id` `min_length>=1`; no `us_` pattern is required
   (`find_prior` accepts any `source_payload_id`). This is the D58/D59 proof: `find_prior`
   keys on `(tenant, source_payload_id=connector_run_id, payload_sha256, dis_channel="api")`
   within 24h, so a retry with the same `run_key` and the same canned bytes finds the prior
   and returns `duplicate_noop` (or resume): no second bronze row, no second `ingress.ready`,
   no duplicate canonical row. A new `run_key` mints a different id, so a real refresh is
   never deduped away. (Backstop beyond the 24h window: the snapshot hot write is a
   natural-key upsert, so a re-landed identical snapshot re-upserts the same values
   idempotently; the receiver dedup is the primary within-window guard.)
   The receiver NEVER derives this id: the ConnectorPipeline reads `trigger.connector_run_id`
   verbatim into `find_prior(upload_session_id=...)` and mints nothing (D54 trust boundary).
3. Mints a FRESH `trace_id` per invocation via `dis_core` (the sanctioned trace mint). This
   is the producer origin of the trace; the receiver reads it and mints none. On a re-run,
   `trace_id` is fresh but `connector_run_id` is stable, exactly the csv client-retry model
   (fresh trace, stable session id).
4. Assembles the `ConnectorTrigger` (`domains=[CATALOG]`, `cursor=None`).
5. Builds the pipeline via `build_square_pipeline(..., token_store=FakeTokenStore(),
   api=FakeSquareApi())` and calls `run_trigger(pipeline, trigger)`.
6. Prints the `ConnectorOutcome` (disposition, trace_id, bronze_id, next_cursor).

The transport lives in a module clearly distinct from the receiver (adapter/mapping/puller/
pipeline). It is the one place trace_id is minted; any no-trace-mint guard for
`thalamus_square` must be scoped to the receiver modules, excluding the transport.

## Pinned seeded target

The slice acts for one concrete seeded identity (dis-testing fixtures, loaded into
`identity_mirror` by mirror-sync):

- Tenant: `buc-ees`, `tenant_id = 019e5e3c-b5d3-705f-9002-2451c4ca2626`, status ACTIVE.
- Store: `Buc-ee's #101 New Braunfels`, `store_code = TX-101`,
  `store_id = 019e5e3c-b62e-75e6-ad62-529127ae944a`, tenant `buc-ees`, `currency = USD`,
  `tax_treatment = EXCLUSIVE`, status ACTIVE. (This is `PRIMARY_TENANT` / `PRIMARY_STORE`.)
- Source: `source_id = square_pos_v2` (pinned), `channel = api` (provisioned Step 2).
- Template: `template_type = snapshot`, provisioned Step 3 for `(buc-ees, square_pos_v2)`;
  its returned `template_id` is carried on the trigger.

Because the store carries `currency` + `tax_treatment`, enrichment (which reads them from
`identity_mirror.stores` by the trigger's `store_id`) does NOT fail loud.

Routing correctness (correcting the "store_code routing" phrasing): snapshot CSV rows carry
NO store_code column. Store binding is via the trigger's `store_id` (the TX-101 UUID);
enrichment keys off that. The streaming consumer's `load_active_mapping` keys on
`(tenant_id, source_id, template_id, status=ACTIVE)`, so the ROUTING to confirm is that the
trigger's `(tenant_id, source_id, template_id)` equals the provisioned source + ACTIVE
template. `store_code` is human-readability only (the optional trigger `store_code` field),
never a routing or enrichment key.

## Steps (new vs reused)

1. Prerequisite identity: `make run-local` (which runs `sync`). REUSED. Loads
   `identity_mirror` tenant plus store with `currency` and `tax_treatment` from the CM
   stand-in. (The seeder is NOT the identity loader; correction above.)
2. Provision source: `POST /sources` `channel="api"` for the seeded tenant. REUSED endpoint.
   NEW artifact: the request body (a small provisioning helper or documented call).
3. Provision template: `POST /mapping-templates` `template_type="snapshot"`, hand-authored
   columns mapping the Square snapshot header keys (`sku_id`, `product_name`,
   `current_retail_price`, and the rest of `SNAPSHOT_HEADER`) to the same canonical dest
   keys. REUSED endpoint. NEW artifact: the hand-authored create body. Capture the returned
   `template_id`.
4. Trigger transport: NEW. The CLI above, run once against the FAKE SquareApi.
5. Verify canonical: REUSED pipeline. The transport publishes `ingress.ready`; the inherited
   streaming consumer (running in the stack, unchanged) consumes it and writes
   `canonical.store_sku_current_position` for the seeded store. Assert the rows.
6. ver2 auth-viability fix: NEW, minimal. The dev token already carries `user_type`/`iss`/
   `aud` and round-trips through the BFF verifier (no claim-shape change). The two real
   fixes: (a) point the `/api` proxy at the BFF (8080); (b) add a dev persona for the seeded
   buc-ees tenant carrying the INTERNAL UUIDs (tenant_id + store_id below), `user_type=TENANT`,
   so `tenant_uuid_of` parses it and RLS/FK resolve. No RS256/JWKS, no full Auth0 login.
7. ver2 onboarding screen: NEW, minimal. One screen calling `POST /sources` plus
   `POST /mapping-templates`, then rendering `GET /connector-health`.

## Tests to specify (not implemented here)

- Unit (offline, no DB, no wall-clock): the transport builds a valid `ConnectorTrigger`, and
  `mint_connector_run_id` proves BOTH properties:
  - (a) STABILITY: two calls with the SAME `(tenant_id, store_id, source_id, template_id,
    run_key)` return an EQUAL id. Asserted by direct string equality of the two derived ids,
    so the proof does not depend on time (no wall-clock bucketing).
  - (b) DISTINCTNESS: a call with a DIFFERENT `run_key` (all else equal) returns a DIFFERENT
    id, so a legitimate later refresh is not deduped away. Also assert the id has no time
    dependence (call it twice with a frozen clock unavailable and identical args to the same
    value, since `now()` never enters the derivation).
- Integration (stack): the offline pull (fake SquareApi) lands the expected canonical rows
  in `store_sku_current_position` for the seeded store.
- Integration (stack): RETRY-STABILITY (a) end to end. Run the transport TWICE with the SAME
  `run_key` and the same canned bytes; assert exactly one canonical row set (the second run
  is `duplicate_noop`/resume: no second bronze row, no second `ingress.ready`). The test
  passes the SAME `run_key` literal both times, never a wall-clock value.
- Integration (stack): DISTINCTNESS (b) end to end. Run the transport with a SECOND, NEW
  `run_key` (same identity, same bytes) and assert it is NOT deduped away: it produces a new
  bronze row and re-lands the snapshot (a fresh intended refresh), confirming a later run is
  not permanently collapsed to the bootstrap id.
- ver2: the onboarding screen calls the real BFF endpoints (not fixtures), verified against
  a mocked-fetch to the `/api` paths.

## Known follow-ups (NOT in this slice)

- Fix the `SANDBOX_BASE_UR` naming in `thalamus_square/config.py` (currently the constant is
  `SANDBOX_BASE_URL`; leave any naming change to the separate follow-up).
- Real Square sandbox: `SQUARE_ACCESS_TOKEN` plus the real `SquarePuller` swap (drop the
  fake).
- Auth0-in-Customer-Master (identity SSOT and issuer) is a SEPARATE later build. When it
  lands, wiring it is a token-SOURCE swap only: replace `verify_token` (BFF
  `auth/verifier.py`) and ver2 `auth/verifyToken.ts` from HS256-shared-secret to RS256/JWKS
  against the CM key set. The claim contract (`user_type`, `iss https://customer-master.local`,
  `aud dis`, `sub`, `exp`), the `Identity` shape, and `scope.py` are UNCHANGED; the dev token
  used in this slice already matches that contract. Full ver2 Auth0 SPA login is part of that
  later build. NOT in this slice.
- A scheduled trigger transport (replacing the manual CLI).
- `infra/_import` consolidation.

## File tree (what this slice would create or edit)

```
connectors/
  SLICE_E2E.md                                              (this brief)
  thalamus-square/
    src/thalamus_square/
      fakes.py            NEW  FakeSquareApi (canned catalog+inventory) + FakeTokenStore
      dev_transport.py    NEW  the CLI producer (mint ids, build trigger, run_trigger)
      provisioning.py     NEW  the POST /sources + POST /mapping-templates request bodies
                               (hand-authored snapshot template), shared by the CLI + tests
    tests/
      unit/
        test_dev_transport.py       NEW  valid trigger + stable connector_run_id (offline)
      integration/
        test_e2e_snapshot.py        NEW  offline pull -> canonical; re-run dedups (stack)
dis/services/dis-ui-ver2/
  vite.config.ts                    EDIT proxy default target -> 8080
  src/auth/dev/personas.ts          EDIT add a seeded buc-ees TENANT persona (internal UUIDs;
                                         user_type already in the token, no claim-shape change)
  src/routes/OnboardSquare.tsx      NEW  onboarding screen (sources + templates + health)
  src/lib/<bff client>              EDIT/NEW  typed calls for the three endpoints
```

The three BFF endpoints and the streaming consumer are REUSED unchanged. The only backend
new code is the transport, the fake, and the provisioning bodies under `connectors/`; the
only dis edits are the two minimal ver2 auth-viability fixes plus the new screen.

## Gate posture

mypy --strict, import-linter, and tests must pass through the Makefile targets when built.
The import-linter forbidden contracts (thalamus_square and thalamus_connector_sdk must not
import dis_mapping / dis_validation / dis_enrichment) continue to hold: the transport and
fake import only the SDK types and the Square receiver, never the pure pipeline libs.

## Open / unresolved

Status: PLAN ONLY. None of this slice is implemented. No spine, no ver2 screen, no BFF
activation lifecycle, no tests exist; the working tree carries only this document.

Unresolved gates (must be answered before any code):

1. Activation model. Option A (STAGED-create plus a new activate endpoint that fires
   `mapping.changed`) does not exist and conflicts with D88 (create-as-ACTIVE); it needs a
   recorded decision extending or superseding D88 before it can be coded, and it is a
   backend slice, not a UI-screen step. Option B (ver2 calls the existing create-as-ACTIVE
   endpoint) reaches the same canonical outcome with no D88 change and no new endpoints,
   because the streaming consumer reads the ACTIVE mapping per-lookup by `template_id`
   (no `mapping.changed` needed). Choice pending.
2. Spine not built. Steps 1-5 (the trigger transport, the fake SquareApi, the offline pull)
   were never written; steps 6-7 depend on them.
3. Target identity. The correct seeded target is store `W-001`
   (`store_id 019e5e3c-b633-7344-93c7-83fb205285ea`, zabka-group, PLN / INCLUSIVE), NOT
   `zab-waw-001` / `WAW-001`, which does not exist in the seed or live identity_mirror.

Deferred follow-ups (record, do not implement in this slice):

- Scheduled or real trigger transport (a screen-fired or cron-driven pull); the orchestrator
  owns the trigger producer, the receiver only consumes triggers.
- Real Square sandbox: `SQUARE_ACCESS_TOKEN` plus the real `SquarePuller` swap (drop the
  fake), and the `SANDBOX_BASE_UR` naming typo in `thalamus_square/config.py`.
- Full Auth0-in-Customer-Master (SPA login plus RS256 / JWKS verification) replacing the
  HS256 dev-auth mode; the swap is at `verifier.py` (BFF) and `verifyToken.ts` (ver2), with
  the claim contract and Identity shape unchanged.
- `infra/_import` consolidation.
