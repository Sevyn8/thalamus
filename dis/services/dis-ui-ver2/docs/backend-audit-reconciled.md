# dis-ui-ver2: Surface-to-Backend Audit (reconciled)

Reconcile of the frontend surface worksheet against the **real** backend. Read-only audit; no code changed.

## Backends audited

Two divergent codebases exist (a fork, not one repo):

- **In-repo contract (authoritative for what dis-ui-ver2 targets):**
  `services/dis-ui-server` at HEAD `9130f02` (`github.com/Sevyn8/ithina-retail-dis`). HS256 dev-stub verifier, Slice-17b `user_type`. dis-ui-ver2's HS256 stub tokens match THIS backend.
- **Deployed / running :8080:** `/home/neerj/sevyn8-fresh/cortex-dis/services/dis-ui-server` (`github.com/Sevyn8/cortex-dis`, HEAD `26a419a`). Auth0 + RS256/JWKS, roles from Customer Master, `require_super_admin`. **Superset** of the in-repo routes: adds `GET /me/roles` and an `/atlas/*` schema-authoring subsystem (super-admin only).

Status below is classified against the **in-repo** `services/dis-ui-server` (the contract v2's tokens work against) + the DIS Postgres schema. The deployed superset does **not** change any tenant-surface row here (its extra routes — `/me/roles`, `/atlas/*` — don't map to these requirements), except: the worksheet anchor "no `/me`" is **stale vs deployed** (see anchors).

## Real API surface (in-repo dis-ui-server, `/api/v1` prefix + root probes)

| Method | Path | Auth |
|---|---|---|
| GET | /mapping-templates | require_read_scope |
| GET | /mapping-templates/{template_id} | require_read_scope |
| POST | /mapping-templates (201) | require_write_scope + resolve_acted_for(body.acting_for_tenant_id) |
| PATCH | /mapping-templates/{template_id} | require_write_scope + resolve_acted_for(body.acting_for_tenant_id) |
| POST | /csv-uploads (201) | require_tenant |
| POST | /mapping-suggestions | require_tenant |
| GET | /dashboard/metrics | require_read_scope |
| GET | /template-types | get_current_identity |
| GET | /template-mapping-fields | get_current_identity |
| GET | /stores-onboarded | require_tenant |
| GET | /quarantine | require_read_scope |
| GET | /quarantine/{item_id} | require_read_scope |
| GET | /healthz, /readyz | none (probes) |

**Deployed adds (cortex-dis):** `GET /me/roles` (get_current_identity), `/atlas/verticals/{vertical}/draft` POST, `/atlas/drafts` GET, `/atlas/drafts/{id}` GET/PATCH, `/atlas/drafts/{id}/publish` POST (all `require_super_admin`).

## DB tables (DIS Postgres schema)

`audit.events` · `bronze.data_ingress_events` · `canonical.store_sku_current_position` · `canonical.store_sku_change_events` · `canonical.store_sku_sale_events` · `canonical.store_sku_signal_history` · `config.source_mappings` (status DRAFT/STAGED/ACTIVE/DEPRECATED, version_seq_per_source, predecessor_version_id, created_by_user_id, mapping_rules) · `identity_mirror.tenants` · `identity_mirror.stores` · `quarantine.quarantined_rows` · `quarantine.quarantined_chunks` · `staging.*` (mirror of canonical). dis-ui-server SQLAlchemy models: `tenants`, `stores`, `quarantined_rows`, `quarantined_chunks`, `source_mappings`.

## Known-anchor check (worksheet §92)

1. **Mapping templates CRUD + scopes — CONFIRMED.** GET list/detail (`require_read_scope`), POST/PATCH (`require_write_scope` + `resolve_acted_for` + `acting_for_tenant_id`), `handlers/mapping_templates.py`. Backed by `config.source_mappings` (full version lineage, status vocab).
2. **`csv_uploads` — CONFIRMED but scope corrected.** `POST /csv-uploads` (201) exists (`handlers/csv_uploads.py`) — but it is **`require_tenant`, NOT `require_write_scope`**. The worksheet's "PLATFORM upload path via require_write_scope" is **stale**: it's a TENANT-scoped write with no PLATFORM impersonation path.
3. **RLS tenant/platform scoping — CONFIRMED.** Two-GUC via `db.py` `write_session`/`rls_session`/`rls_platform_session`; tenant-pinned WITH CHECK. Applies to every read/write.
4. **No `/me` — CONFIRMED in-repo; STALE vs deployed.** No `/me` in `ithina-retail-dis`. Deployed cortex-dis exposes `GET /me/roles` (roles resolved from Customer Master). v2's fixture-only `getMe` has a real counterpart in production.

## Auth posture per write route (for the frontend)

- **POST/PATCH /mapping-templates:** `require_write_scope` → `resolve_acted_for(scope, body.acting_for_tenant_id)`. TENANT must omit `acting_for_tenant_id` (pinned; sending one → 403). PLATFORM+`dis:ops` must send it (impersonation; absent → 403).
- **POST /csv-uploads, POST /mapping-suggestions:** `require_tenant` (TENANT identity required; no impersonation).
- **Reads** (`/dashboard/metrics`, `/quarantine*`, `/mapping-templates*`): `require_read_scope` — PLATFORM see-all requires `user_type=PLATFORM` AND `dis:ops`; TENANT pinned to own tenant.

## Reconcile worksheet (Status + Evidence filled)

Status: EXISTS (bucket 1) / DATA-EXISTS-NO-API (bucket 2) / NEW-BACKEND (bucket 3) / PARTIAL (split).

| Domain | Requirement (from surface) | R/W | Status | Evidence (route/file/model) |
|---|---|---|---|---|
| Pipelines | list with method/schedule/next-run/quality/status | R | PARTIAL | template/source list via GET /mapping-templates + per-template `rows_24h`/`last_received_at` in `handlers/dashboard.py`; schedule/method/next-run/quality%/status **not modeled** (no pipeline table) |
| Pipelines | detail | R | PARTIAL | GET /mapping-templates/{id} covers the mapping side; pipeline/schedule/run fields not modeled |
| Pipelines | create pipeline from confirmed mapping | W | PARTIAL | mapping persist EXISTS (POST /mapping-templates); connector/pipeline provisioning NEW (no model) |
| Pipelines | settings update | W | NEW-BACKEND | no pipeline model/route |
| Runs | list with method filter | R | DATA-EXISTS-NO-API | `bronze.data_ingress_events` + `audit.events` hold ingress/stage events; no runs route or run-aggregate model |
| Runs | run detail + stages + progress | R | PARTIAL | per-trace stage events in `audit.events`; no run-detail route, progress not modeled |
| Runs | accepted/revised/rejected counts | R | DATA-EXISTS-NO-API | rejected = `quarantine.quarantined_rows`; accepted/revised derivable from `bronze`/`canonical.*`; no per-run counts route (dashboard is 24h aggregate only) |
| Runs | records / needs-review views | R | PARTIAL | needs-review EXISTS via GET /quarantine (+/{item_id}); records view = `canonical.*` tables, no read route |
| Runs | export | R | NEW-BACKEND | no route |
| Data quality | outcome classification per run | R | DATA-EXISTS-NO-API | `quarantine.*` + `audit.events`; no per-run outcome route |
| Data quality | issues-by-type aggregation (24h) | R | PARTIAL | dashboard 24h quarantine count EXISTS (`handlers/dashboard.py`); by-type breakdown = `quarantined_rows` reason columns, no route |
| Data quality | gate failures per run | R | PARTIAL | GET /quarantine/{item_id} returns per-item failure detail; per-run grouping not modeled |
| Data quality | raw sample vs canonical output | R | PARTIAL | raw payload in `quarantined_rows` (quarantine detail route); canonical output in `canonical.*` (no read route) |
| Data quality | resolve / apply-rule / skip-rows | W | NEW-BACKEND | quarantine is read-only in dis-ui-server; no resolve route (drainer is a separate service) |
| Data quality | retry / reprocess / bulk retry | W | NEW-BACKEND | no route |
| Data quality | assign owner | W | NEW-BACKEND | no owner column/route |
| Data quality | dismiss with reason | W | NEW-BACKEND | no route |
| Data quality | error-report export | R | NEW-BACKEND | no route |
| Connect-source | test connection | W | NEW-BACKEND | no route |
| Connect-source | discover fields | R | NEW-BACKEND | no field-discovery route (client supplies columns to /mapping-suggestions) |
| Connect-source | mapping proposal + confidence | R | EXISTS | POST /mapping-suggestions (`handlers/mapping_suggestions.py`) → per-column suggestions + `source` (llm/fallback) |
| Connect-source | parsing profile confirm | W | EXISTS | persisted as MappingColumn fields (src_datetime_format / decimal / thousand / is_percentage) via POST /mapping-templates (`schemas/mapping_templates.py`) |
| Connect-source | go live | W | PARTIAL | mapping create + activation via template lifecycle EXISTS (`config.source_mappings` status); pipeline provisioning NEW |
| Connector health | per-connector reachability/last-contact | R | PARTIAL | `last_received_at` per template in dashboard flow; per-connector reachability/last-contact NEW (no connector model) |
| Schema drift | drift feed | R | NEW-BACKEND | no drift model/route |
| Schema drift | field-change diff | R | NEW-BACKEND | no drift model/route |
| Schema drift | shadow comparison | R | NEW-BACKEND | no shadow route |
| Schema drift | approve / reject proposed mapping | W | PARTIAL | mapping promotion via template lifecycle (`config.source_mappings` status vocab); drift-approval workflow NEW |
| Canonical explorer | query canonical entity | R | DATA-EXISTS-NO-API | `canonical.store_sku_current_position` (+ change/sale/signal); no read route |
| Canonical explorer | record fetch (all fields) | R | DATA-EXISTS-NO-API | `canonical.*` tables; no route |
| Canonical explorer | per-field lineage | R | DATA-EXISTS-NO-API | canonical rows carry `mapping_version_id` → `config.source_mappings.mapping_rules`; no lineage route |
| Mapping templates | list | R | EXISTS | GET /mapping-templates (`handlers/mapping_templates.py`) |
| Mapping templates | detail | R | EXISTS | GET /mapping-templates/{template_id} |
| Mapping templates | versions and lifecycle | R | EXISTS | GET /{id} returns `versions[]` + active/staged/draft (`schemas/mapping_templates.py`); `config.source_mappings.status` |
| Mapping templates | create version / promote / rollback | W | PARTIAL | create EXISTS (POST /mapping-templates); PATCH edits/mints DRAFT; explicit promote(→ACTIVE)/rollback transition not a confirmed route (status vocab exists in `config.source_mappings`) |
| Mapping templates | shadow test | W | NEW-BACKEND | no shadow route (`pre/post_validation_suite_ref` columns exist, no shadow-run API) |
| Mapping templates | reprocess | W | NEW-BACKEND | no route |
| Mapping templates | version diff | R | PARTIAL | raw versions + rules served by GET /{id}; no server-side diff endpoint (client computes) |
| Credentials | list + expiry state | R | NEW-BACKEND | no credentials model/route (secrets live in GCP Secret Manager / terraform secrets module, not a DB-exposed API) |
| Credentials | add | W | NEW-BACKEND | no route |
| Credentials | rotate | W | NEW-BACKEND | no route |
| Credentials | revoke | W | NEW-BACKEND | no route |
| Audit | event log filtered read | R | DATA-EXISTS-NO-API | `audit.events` (`schemas/postgres/audit/events.sql`); no audit route in dis-ui-server |
| Audit | export | R | NEW-BACKEND | no route |
| Notifications | routing rules read | R | NEW-BACKEND | no model/route |
| Notifications | channels read | R | NEW-BACKEND | no model/route |
| Notifications | escalation history | R | NEW-BACKEND | no model/route |
| Notifications | add / configure rule, toggle | W | NEW-BACKEND | no model/route |

## Bucket summaries

### Bucket 1 — Wire now (EXISTS): 5 rows
- Connect-source: mapping proposal + confidence → `POST /mapping-suggestions`
- Connect-source: parsing profile confirm → `POST /mapping-templates` (MappingColumn parse fields)
- Mapping templates: list → `GET /mapping-templates`
- Mapping templates: detail → `GET /mapping-templates/{id}`
- Mapping templates: versions and lifecycle → `GET /mapping-templates/{id}` (versions[] + active/staged/draft)

(Plus the EXISTS half of PARTIAL rows: quarantine list/detail already serve "needs-review" and "gate failures per item"; dashboard 24h metrics; template create.)

### Bucket 2 — New API over existing data (DATA-EXISTS-NO-API): 7 rows
- Runs: list with method filter → `bronze.data_ingress_events` + `audit.events`
- Runs: accepted/revised/rejected counts → `quarantine.*` + `bronze`/`canonical.*`
- Data quality: outcome classification per run → `quarantine.*` + `audit.events`
- Canonical explorer: query canonical entity → `canonical.store_sku_current_position` (+ change/sale/signal)
- Canonical explorer: record fetch (all fields) → `canonical.*`
- Canonical explorer: per-field lineage → canonical `mapping_version_id` → `config.source_mappings.mapping_rules`
- Audit: event log filtered read → `audit.events`

(Plus the data-backed halves of PARTIAL rows: run stages via `audit.events`; issues-by-type via `quarantined_rows`; raw-vs-canonical via `quarantined_rows` + `canonical.*`; version diff via served versions.)

### Bucket 3 — New backend (NEW-BACKEND): 23 rows
- Pipelines: settings update
- Runs: export
- Data quality: resolve/apply-rule/skip-rows; retry/reprocess/bulk retry; assign owner; dismiss with reason; error-report export
- Connect-source: test connection; discover fields
- Schema drift: drift feed; field-change diff; shadow comparison
- Mapping templates: shadow test; reprocess
- Credentials: list+expiry; add; rotate; revoke
- Notifications: routing rules read; channels read; escalation history; add/configure/toggle

(Plus the new-functionality halves of PARTIAL rows: pipeline/connector provisioning; per-connector reachability; drift approve/reject workflow; explicit promote/rollback transitions.)

### PARTIAL (split): 13 rows
Pipelines list; Pipelines detail; Pipelines create-from-mapping; Runs detail+stages+progress; Runs records/needs-review; Data-quality issues-by-type; Data-quality gate-failures-per-run; Data-quality raw-vs-canonical; Connect-source go-live; Connector-health reachability; Schema-drift approve/reject; Mapping-templates create/promote/rollback; Mapping-templates version-diff. Each row's EXISTS / DATA-EXISTS / NEW split is in the Evidence column above.

## Counts

- Total requirement rows: **48** (worksheet said "49"; the table holds 48).
- EXISTS: **5** · DATA-EXISTS-NO-API: **7** · NEW-BACKEND: **23** · PARTIAL: **13**.

## D37 identity seam (surfaced during mapping-templates wiring)

- Both `dis-ui` and `dis-ui-ver2` carry a stale fixture identity scheme: `personas.ts` and
  `ME_FIXTURES` key on **external ids** (`u_acmeuser0001`, `anjali`), while the tokens that
  actually authenticate against the real backend carry **auth0 subs** (`auth0|...`) plus
  **UUID `tenant_id`s**. The three id-spaces do not agree: persona `sub`, fixture key, and
  token `sub` are all different.
- `dis-ui` never hits this because it runs **real mode**, where `getMe()` throws by design and
  never reads `ME_FIXTURES`. `dis-ui-ver2` surfaced it only because it added a **fixture-mode
  DevLogin test** that exercises the profile lookup.
- Additionally, both frontends' dev tokens **predate the Slice-17b `user_type` claim** in their
  committed form. The working local smoke used **freshly minted v1 tokens** (carrying
  `user_type` plus the local seeded tenant UUIDs), not the stale committed ones.
- **Decision needed (D37):** pick ONE identity scheme for dev/fixtures (external-id vs
  auth0-sub/UUID) and reconcile `personas.ts` + fixtures across **both** `dis-ui` and
  `dis-ui-ver2` together, so they stop diverging. This is a **shared** decision, not a
  v2-only change.
