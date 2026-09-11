# Thalamus Architecture

Current, implemented architecture only. Anything not listed here is not deployed.
Single environment: GCP project `sevyn8-thalamus-staging`, region `asia-south1`,
wired in `infra/envs/staging/main.tf`. Image versions are pinned as variable
defaults in `infra/envs/staging/variables.tf`.

## Subsystems

- **Customer Master (CM)** — `cm-backend/` (FastAPI) + `cm-frontend/` (Next.js).
  Owns identity, tenants, stores, org trees, RBAC, onboarding, tenant documents,
  channel-credential *names*. The system of record for who exists.
- **DIS** — `dis/` (uv workspace root; libraries in `dis/libs`, services in
  `dis/services`). Owns data ingestion: bronze capture, mapping, validation,
  canonical retail data, quarantine, audit, telemetry.
- **Synapse** — `synapse/`. The analytics/actions plane: a daily orchestrator
  resolves declared analyses over canonical data and appends actions. Peer of
  DIS with its own migration chain and DB roles. Currently shadow-only: it
  records actions and delivers nothing itself.
- **Axon** — `axon/`. The communications/delivery plane: delivery ledger and a
  SendGrid email adapter. Holds addresses and send state only; identity stays
  with CM.
- **Connectors** — `connectors/`. POS pulls (Square, Clover) built on a shared
  SDK; run as Cloud Run jobs that feed the DIS pipeline.
- **Contracts** — `dis/contracts/` (Pub/Sub message schemas, live) and
  `contracts/` (Cortex contract set; only `pack/` and `synapse/` are authored,
  each with a manually run `validate.py` harness).

## Deployables

HTTP services (Cloud Run):

| Service | Code | Notes |
|---|---|---|
| cm-backend | `cm-backend/` | FastAPI; `core` schema |
| cm-frontend | `cm-frontend/` | Next.js; calls cm-backend and synapse-ui-server |
| dis-ui-server | `dis/services/dis-ui-server` | FastAPI BFF for DIS UI; CSV upload, quarantine, audit, mappings, connector OAuth |
| dis-ui-ver2 | `dis/services/dis-ui-ver2` | Vite/React SPA served by nginx; proxies `/api` to dis-ui-server |
| synapse-ui-server | `synapse/services/synapse-ui-server` | Starlette superadmin console BFF; invoker restricted to the platform SA (no `allUsers`) |

Pub/Sub pull consumers (Cloud Run services running a poll loop):

| Service | Consumes |
|---|---|
| csv-ingest-worker | `dis-csv-received-sub` |
| streaming-consumer | `dis-ingress-ready-sub` |
| axon-sender | `axon-send-requested-sub` (ingress INTERNAL_ONLY) |

Cloud Run jobs: `square-connector`, `clover-connector`, `mirror-sync-consumer`
(all manually executed), `synapse-orchestrator` (the only scheduled workload —
daily Cloud Scheduler trigger), and one `migrate-*` job per migration chain
(`migrate-cm`, `migrate-dis`, `migrate-synapse`, `migrate-axon`).

## Data stores

One Cloud SQL PostgreSQL 16 instance (`thalamus-pg`), one database (`thalamus`),
four independent Alembic chains with separate version tables:

| Chain | Version table | Owns schemas |
|---|---|---|
| `cm-backend/migrations` | `alembic_version` in the CM schema (`core`) | `core` |
| `dis/alembic` | `alembic_version` | `bronze`, `canonical`, `staging`, `quarantine`, `config`, `identity_mirror`, `audit`, `telemetry` |
| `synapse/alembic` | `synapse_alembic_version` | `synapse` |
| `axon/alembic` | `axon_alembic_version` | `axon` |

Database roles are per plane: `user_admin_backend` (CM), `ithina_dis_user` (all
DIS writes; NOSUPERUSER NOBYPASSRLS), `dis_mirror_reader` (SELECT on CM's
`core.tenants`/`core.stores` only), `synapse_reader` (SELECT on the two
canonical event tables + identity mirror), `synapse_writer` (INSERT-only into
the synapse action log — it cannot SELECT, so "resolvers never write" is a
runtime property), plus axon sender/reader roles. Terraform creates the core
roles; `infra/db-setup/sql/01–09` are hand-applied privileged grants.

GCS: `thalamus-dis-bronze-staging` (bronze CSV objects) and
`sevyn8-thalamus-cm-documents-staging` (CM tenant documents via V4 signed URLs).

Pub/Sub (all provisioned topics; each main subscription has a dead-letter
topic + subscription retaining 31 days):

| Topic | Consumer | Max delivery attempts |
|---|---|---|
| `dis-csv-received` | csv-ingest-worker | 20 |
| `dis-ingress-ready` | streaming-consumer | 100 |
| `axon-send-requested` | axon-sender | 5 (email send is not idempotent) |

`dis/contracts/pubsub` also defines `identity.changed`, `mapping.changed`,
`ingress.resubmit`, `pipeline.dlq`, and `quarantine` schemas — those topics are
**not provisioned**; the schemas are contract-only. BigQuery DDL under
`dis/schemas/bigquery` and the `dis/dbt` skeleton are not deployed.

## Major flows

**CSV ingestion.** `POST /api/v1/csv-uploads` on dis-ui-server authenticates,
writes the object to bronze GCS, then publishes `csv.received` (write before
publish). csv-ingest-worker pulls it: path cross-check → download + sha256 →
dedup lookup → DuckDB preflight → PII gate → one metadata-only
`bronze.data_ingress_events` row → publish `ingress.ready` → mark published.
The worker owns the bronze row; the upload handler never writes it.

**Canonical write.** streaming-consumer pulls `ingress.ready`: fetch bronze row
+ GCS object → load the ACTIVE mapping from `config.source_mappings` →
pre-validation → pure mapping engine → post-validation → atomic dual write
(hot-position upsert + event insert). Failures are audited and nacked, except a
narrow allowlist of deterministic failures which land in `quarantine.*` and are
acked.

**Connectors.** One Cloud Run job execution = one trigger; tenant/store/source/
template identity is trusted from the trigger args. The SDK pipeline extracts
from the POS API, serializes CSV, uploads to bronze GCS, reuses the
csv-ingest-worker bronze module for dedup/insert/mark-published, and publishes
`ingress.ready` directly (connectors skip the `csv.received` hop). OAuth
connect flows live in dis-ui-server; connectors refresh tokens from Secret
Manager.

**Mirror-sync.** A run-to-completion job (not Pub/Sub, despite the `-consumer`
name): reads CM's `core.tenants`/`core.stores` directly as `dis_mirror_reader`
under PLATFORM RLS context — the only place DIS reads a CM schema — and
upserts `identity_mirror.tenants`/`identity_mirror.stores`, one transaction per
tenant, never deleting.

**Synapse.** The daily orchestrator sweeps active `synapse.provision` rows;
per due slot it claims a row in `synapse.run`, resolves the declared analysis
(resolvers read `canonical.store_sku_sale_events`/`store_sku_change_events` as
`synapse_reader`), and appends actions/events as `synapse_writer`. A re-run of
a claimed slot is a no-op. synapse-ui-server is the read-mostly superadmin
console; its enable route publishes to `axon-send-requested` and authorizes by
delegating to cm-backend's `GET /api/v1/me/can-do`.

**Axon.** The producer (synapse-ui-server) mints the `delivery_id` and
publishes the envelope; axon-sender drains the subscription, sends via
SendGrid, and inserts the ledger row into `axon.platform_deliveries`. The
producer-minted id is the primary key, so a redelivered message is refused by
unique violation (the INSERT-only role cannot SELECT, so a unique-violation
catch, not ON CONFLICT, is the idempotency mechanism). CM writes
`axon.channel_connections` (credential names, never credential values) as its
single reach into the axon schema; tenant-facing channels are schema-only
rails today.

## Canonical data ownership

`canonical.*` is owned by the DIS chain and written **only** by
streaming-consumer (atomic dual write in `sinks/canonical.py`). Readers:
synapse resolvers, dis-ui-server. `canonical.store_sku_signal_history` and the
`staging.*` tables have DDL but no writer anywhere in the codebase.
`identity_mirror.*` is written by mirror-sync and read by dis-ui-server and
streaming-consumer. `quarantine.*` is written by streaming-consumer via
dis-quarantine and read/resubmitted through dis-ui-server. `audit.events` is
written by all DIS lanes via dis-audit; `telemetry.connector_health` is
upserted by csv-ingest-worker and the connector SDK.

## Idempotency and transaction invariants (as implemented)

- **Bronze dedup:** key `(tenant, dis_channel, upload_session_id,
  payload_sha256)` within a 24-hour window measured against the prior row's
  server-side `received_at`. A PUBLISHED or FAILED prior row makes
  the whole run a no-op returning the prior trace; a RECEIVED-unpublished prior
  is resumed (re-publish, no second row). Shared by csv-ingest-worker and the
  connector SDK.
- **Canonical event insert:** `ON CONFLICT DO NOTHING` on
  `(tenant_id, store_id, source_id, source_event_id, row_hash)`, so redelivery
  cannot duplicate events; corrections (same event, different row hash) still
  append.
- **Hot-position upsert:** natural-key arbiter, event-time-wins with `>=` so an
  exact-tie redelivery is idempotent; groups are sorted by natural key to avoid
  deadlocks; EVENT projections require an existing position row and raise
  loudly on a miss.
- **Write-then-publish ordering everywhere:** the GCS object precedes
  `csv.received`; the bronze row precedes `ingress.ready`.
- **Axon ledger:** producer-minted `delivery_id` as PK (see above). The send
  itself is not idempotent — a crash between the SendGrid 202 and the ledger
  commit can duplicate an email, bounded by the subscription's 5 delivery
  attempts.
- **Mirror-sync:** upsert-only, parent-before-children, per-tenant
  transactions, no deletes.

## Pipeline library invariants

- **Mapping** (`dis-mapping`): `mapping_rules` applies ordered stages
  `rename → normalize → cast → derive`; numeric parsing requires explicitly
  declared locale separators (construction fails loud when omitted). The engine
  never sees consumer-injected fields (`tenant_id`, `store_id`, `trace_id`,
  `mapping_version_id`).
- **Validation** (`dis-validation`): two gates — source-shape before mapping
  (permissive about extra columns) and canonical-shape after mapping
  (`strict=True`); `assert_no_drift` errors (never skips) on any
  model/suite-partition mismatch.
- **Enrichment** (`dis-enrichment`): pure, no I/O; runs after mapping and
  before post-validation, and its output overwrites the mapping's value for
  registered fields (`currency`, `tax_treatment` come from
  `identity_mirror.stores`).
- **Audit vs quarantine** (`dis-audit` / `dis-quarantine`): audit is
  fire-and-forget (a failed audit write never blocks or changes the data
  path); quarantine is fail-loud (`QuarantineWriteError` — the caller must
  nack, never ack-and-lose). The two correlate by `trace_id` +
  `data_ingress_event_id`.
- **Canonical models** (`dis-canonical`): hand-aligned to the live schema, not
  code-generated; schema drift is guarded by the dis-audit drift check
  (type/nullability/length) and validation suites, not by codegen.
- **Identifiers** (`dis-core`): tenant/store identity is the internal UUID
  end-to-end; external display codes ride along as data only.

## Tenancy (summary — see SECURITY.md)

Tenant context reaches the database exclusively as transaction-local GUCs
(`app.tenant_id`, `app.user_type`) set via `set_config(..., true)`. TENANT
sessions see one tenant; PLATFORM sessions with a NULL tenant see everything
read-only; tenant-scoped tables in every plane carry FORCE RLS with a
`tenant_isolation` policy. Both CM and DIS engines assert NOBYPASSRLS and the
expected database at first use.
