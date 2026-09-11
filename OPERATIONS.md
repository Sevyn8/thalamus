# Thalamus Operations

Single environment: GCP project `sevyn8-thalamus-staging`, region `asia-south1`.
All infrastructure is Terraform under `infra/envs/staging` (state in the shared
`sevyn8-tfstate` bucket, prefix `thalamus/staging`). There is **no CI**: every
gate in this repository is run by hand (see README for the per-subsystem
commands), and nothing runs the test suites or the contract conformance
harnesses automatically.

## Deployment

Terraform owns every Cloud Run image. Image tags are variable defaults in
`infra/envs/staging/variables.tf`; a `gcloud run deploy` would be reverted by
the next `terraform apply`. The deploy flow for any service is:

1. Build and push the image with its Cloud Build config:
   - cm-backend: `gcloud builds submit --config cm-backend/cloudbuild.yaml`
   - synapse-orchestrator: `gcloud builds submit --config synapse/cloudbuild.yaml --substitutions=_TAG=vN .`
   - synapse-ui-server: `synapse/services/synapse-ui-server/cloudbuild.yaml`
   - DIS images: `dis/terraform/docker/cloudbuild-*.yaml` (dis-ui-ver2,
     mirror-sync-consumer, migrate-dis) and the service Dockerfiles
     (`dis/services/dis-ui-server/Dockerfile`,
     `dis/terraform/docker/*.Dockerfile` for the workers)
   - connectors: `connectors/thalamus-{square,clover}/Dockerfile`
   - axon-sender: `axon/services/axon-sender/Dockerfile`
2. Bump the image tag in `infra/envs/staging/variables.tf`.
3. `terraform plan` / `terraform apply` in `infra/envs/staging`.

Rollback is the same flow with the previous tag: re-pin and apply.

One-time project bootstrap lives in `infra/bootstrap` (local-state Terraform
that creates the project, billing link, and baseline APIs; run once by hand —
it deliberately has no GCS backend because it precedes the remote state).

## Database setup and migrations

One Cloud SQL PostgreSQL 16 instance, one database, four Alembic chains (CM,
DIS, Synapse, Axon — see ARCHITECTURE.md).

Privileged SQL that Terraform deliberately does not run lives in
`infra/db-setup/sql/01–09` and is applied by hand over the Cloud SQL Auth Proxy
(`dis/cloud-sql-proxy/`). Hard ordering:

1. `terraform apply` (instance, database, core roles).
2. `sql/01_extensions_and_uuidv7.sql` as `postgres` (extensions + canonical
   `public.uuidv7()`), before any Alembic.
3. CM Alembic (`migrate-cm` job, or locally `alembic upgrade head` in
   cm-backend) — creates `core.*`.
4. DIS Alembic (`migrate-dis` job; locally `make -C dis db-migrate`).
5. `sql/02_mirror_reader_grant.sql` as `user_admin_backend` (must follow CM's
   migration; `postgres` cannot grant on `core`).
6. The remaining grant files (`03`–`09`: synapse reader/writer, provisioner,
   axon roles, CM's `axon.channel_connections` grant) as their headers state.

Each chain has a Cloud Run job (`migrate-cm`, `migrate-dis`, `migrate-synapse`,
`migrate-axon`) executed with `gcloud run jobs execute <job> --region
asia-south1`. Never edit an applied migration.

Hand-run SQL sessions against tenant-scoped tables must set the RLS GUCs first
(`app.user_type`, `app.tenant_id`) or reads silently return zero rows under
FORCE RLS.

## Scheduled and manual workloads

- `synapse-orchestrator`: the only scheduled workload (Cloud Scheduler, daily).
- `square-connector` / `clover-connector`: manual `gcloud run jobs execute`
  with per-run trigger args (tenant/store/source/template identity).
- `mirror-sync-consumer`: manual run-to-completion job; upsert-only
  reconciliation of `identity_mirror` from CM's tables.

## Health

Every service exposes `GET /healthz` (cm-backend: `GET /api/v1/health`;
dis-ui-server and synapse-ui-server also expose `/readyz`). The Pub/Sub
consumers' health servers report heartbeat freshness: 200 while fresh, 503
when the poll loop stalls.

## Monitoring

`infra/modules/monitoring-alerts` defines one email notification channel and
these policies: dead-letter queue not empty (any `*-dlq-sub`), stuck messages
on the three main subscriptions, Synapse orchestrator execution failed,
Synapse orchestrator absent for over 24 hours, Synapse slots failed
(never-retried run rows), and stale newest-sale age per tenant.
`infra/modules/monitoring-alerts/verify-aggregations.sh` sanity-checks the
alert aggregations against the live project.

Structured logs must carry a `severity` field (not `levelname`/`level`) or
Cloud Logging files them at DEFAULT and no log-based alert can match them.

## Failure lanes and recovery

- Each main subscription has a dead-letter topic/subscription retaining 31
  days (`dis-csv-received`: 20 attempts, `dis-ingress-ready`: 100,
  `axon-send-requested`: 5). There is no automated drain; DLQ contents are
  inspected and replayed by hand.
- Deterministic pipeline failures land in `quarantine.*` tables and are
  visible in the DIS UI (quarantine surface, with resubmit request shapes);
  non-deterministic failures nack and retry.
- Audit trail: `audit.events` (per-stage outcomes, keyed by `trace_id`);
  ingestion runs are derived from it (dis-ui-server runs surface).

## Local development

- DIS (uv workspace root, includes synapse/axon/connectors):
  `make -C dis run-local` (docker compose Postgres + Pub/Sub emulator, topics,
  migrations), `make -C dis check` (pre-flight script), `make -C dis seed`
  (test fixtures). `dis/.env` carries the local defaults the Makefile includes.
- cm-backend: `docker compose up` (local Postgres), `uv sync`,
  `alembic upgrade head`, `scripts/check_setup.sh` for a full pre-flight;
  `scripts/seed_dev_data` loads the dev seed workbook (refuses
  `ENVIRONMENT=production`).
- Frontends: `pnpm install` + `pnpm dev` (cm-frontend, dis-ui-ver2).
- Pipeline integrity checks: `dis/scripts/pipeline-check/README.md` documents
  `create_template.py` / `verify_ingest.py` and their operator traps.

## Type/schema generation

- `cm-backend/scripts/test_endpoints.sh` (and `test_endpoints_max_view.sh`)
  refresh `cm-backend/docs/endpoints/openapi.json` from the running app;
  cm-frontend consumes a copy at `cm-frontend/docs/openapi.json` via
  `pnpm gen:types` → `types/openapi-generated.ts`.
- `cm-backend/docs/schema/current_schema.sql` is the generated schema
  snapshot (`scripts/verify_cloud_schema.py` compares live vs expected).

## Contract conformance

`python3 contracts/conformance/validate.py` (pack contract) and
`cd dis && uv run python ../contracts/synapse/validate.py` (synapse contracts,
also run by `make -C synapse conformance` and covered by a synapse unit test).
Both are manual; nothing schedules them.

## Required external services

Auth0 (issuer/audience for every HTTP service; an Auth0 Action stamps the
`https://sevyn8.com/user_type` and tenant claims), GCP (Cloud Run, Cloud SQL,
Pub/Sub, GCS, Secret Manager, Cloud Build, Cloud Scheduler, Vertex AI for
mapping suggestions), SendGrid (axon-sender), Square and Clover developer
apps (OAuth + API access for the connectors).

## Onboarding a Square tenant (prerequisites)

A Square customer onboards only when all four exist:

1. `identity_mirror.tenants` + `identity_mirror.stores` rows (Mirror Sync from
   Customer Master), with the store carrying `currency` + `tax_treatment`
   (both NOT NULL there; the enrichment source of truth).
2. A `config.sources` row for the source, `channel='api'`.
3. An ACTIVE `config.source_mappings` row, `template_type='snapshot'`, mapping
   the CSV header to `{sku_id, product_name, current_retail_price, ...}`.
4. `telemetry.connector_health` is worker-emitted per run (no
   pre-provisioning needed).

## Smoke and verification

- `cm-backend/scripts/smoke_curl.sh`, `smoke_test.py`,
  `test_endpoints.sh` / `test_endpoints_cloud.sh` (cloud variant writes its
  OpenAPI snapshot to /tmp, never over the local one).
- `cm-backend/scripts/verify_cloud_schema.py` — live schema vs expected.
- `dis/scripts/check_setup.sh` — local stack pre-flight.
