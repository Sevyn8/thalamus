# Thalamus Connectors build brief

Status: APPROVED. Locked decisions below; implementation in progress.

Scope: a vendor-API receiver tier that feeds the EXISTING DIS pipeline via Path A.
Connectors produce template-mappable rows, land them in the bronze bucket as CSV,
write the bronze row, and publish `ingress.ready`. Everything from bronze onward
(streaming-consumer, mapping, validation, canonical write) is inherited and untouched.

First vendor: Square (sandbox).

---

## 1. Path A and the inheritance boundary

A connector run: reads its trigger, authenticates to the vendor, extracts CATALOG /
INVENTORY / ORDERS incrementally (cursor based), shapes each batch into
template-mappable CSV rows, writes its own object to the bronze GCS bucket, writes one
metadata-only bronze row, and publishes `ingress.ready`. From the bronze write onward
the path is the csv-ingest-worker's inherited logic, reused, not reimplemented.

Do NOT touch, and do NOT amend:

- `services/streaming-consumer`, `libs/dis-mapping`, `libs/dis-validation`,
  `libs/dis-enrichment`, `libs/dis-canonical` (referenced only as the target shape).
- Any frozen Pub/Sub contract (`contracts/pubsub/*.schema.json`).

The only existing DIS code that changes is
`services/csv-ingest-worker/src/csv_ingest_worker/bronze.py` (section 5), in a way that
leaves the CSV worker behaviourally identical.

### Trust boundary (D54, hard rule 4)

Identity (`tenant_id`, `store_id`), `trace_id`, and `connector_run_id` are READ off the
trigger and trusted. The connector never mints `trace_id`, never imports
`dis_core.identity` (a test enforces both), and does no external-to-internal
translation. The only id it mints is the bronze row PK via `dis_core.new_uuid7()`.

---

## 2. Payload format is CSV (verified)

The streaming consumer parses every bronze object strictly as CSV:
`streaming-consumer/src/streaming_consumer/pipeline/fetch.py:148` calls
`pl.read_csv(io.BytesIO(data), separator=separator, infer_schema=False)`, with
`separator=event.delimiter` (fetch.py:188) read off `IngressReadyEvent.delimiter`
(envelope.py:57). There is no content-type dispatch and no JSON path.

So the connector:

- serializes each extracted batch to comma-delimited CSV bytes,
- writes a header row whose column names are the `store_sku_current_position` template
  field keys (`sku_id`, `sku_variant`, `barcode`, `product_name`, `product_category`,
  `current_retail_price`, `unit_cost`, `promo_price`, `currency`, `stock_qty`,
  `reorder_point`, `receipt_date`, `expiry_date`, `sku_status`, `store_code`, and so
  on). The CSV header is the interface to the mapping template.
- writes the object as `{trace_id}.csv` via `dis_storage.build_object_path(ext="csv")`
  and `StorageClient.upload_bytes(content_type="text/csv")`. This keeps the consumer's
  `pl.read_csv` and the `ingress.ready` `gcs_uri` regex (`.csv|json`) unchanged.
- sets `ingress.ready.delimiter=","` explicitly, matching exactly what it serialized.
  No downstream detection is relied on.

Provenance and format are separate fields: `dis_channel="api"` (provenance, API pull),
`content_type="text/csv"`, extension `.csv` (format).

`'api'` is already in `ck_bdie_dis_channel_vocab`
(`csv_upload, api, csv_erp, reverse_api`) and `content_type` is `VARCHAR(64) NULL`, so
neither needs a migration.

When a Square source is provisioned, `config.sources.dis_channel='api'` is set (reuses
the bronze vocabulary; drives the ingestion mode). This is a config.sources
provisioning concern, owned outside the receiver hot path.

---

## 3. Workspace: two new members

Added to `dis/pyproject.toml` members and `[tool.uv.sources]`:

| Path | Package | Role |
|------|---------|------|
| `connectors/sdk` | `thalamus_connector_sdk` | adapter Protocol, ConnectorPipeline, trigger, reason codes, CSV serialize, config |
| `connectors/thalamus-square` | `thalamus_square` | Square adapter (auth, discover, extract, preflight, mapping, main) |

Both packages join the `MYPY_PACKAGES` and import-linter gate lists in the same commit
that clears them. `uv sync` is run to confirm the sibling `../connectors/*` members
resolve; if uv rejects the `..` member paths, the fallback is explicit path sources for
the reused dis packages (resolver wiring only, no design change).

The SDK reuses csv-ingest-worker's bronze and publisher seams, so its runtime closure
mirrors the worker's: `csv-ingest-worker`, `dis-core`, `dis-rls`, `dis-storage`,
`dis-audit`, and transitively `dis-pii`; plus `pydantic`, `sqlalchemy[asyncio]`,
`psycopg[binary]`, `google-cloud-pubsub`. `thalamus_square` depends on
`thalamus_connector_sdk` plus `httpx`.

Design debt noted: depending on the csv-ingest-worker service package from the SDK is a
smell. The clean end state is extracting `bronze.py` and `publisher.py` into a shared
lib. That extraction is out of scope here; we reuse in place.

---

## 4. Adapter Protocol (`thalamus_connector_sdk`)

A structural Protocol; tests inject fakes, production never imports test doubles.

```python
class ConnectorAdapter(Protocol):
    def authenticate(self, trigger: ConnectorTrigger) -> AuthContext: ...
    def discover(self, auth: AuthContext) -> Discovery: ...
    def extract(self, auth: AuthContext, domain: Domain, cursor: Cursor | None) -> ExtractResult: ...
    def preflight(self, extract: ExtractResult) -> PreflightResult: ...
```

- `Domain` is a closed `StrEnum`: `CATALOG | INVENTORY | ORDERS`.
- `discover` returns locations plus the vendor native schema, to seed a template
  proposal.
- `extract` is cursor-based incremental. `ExtractResult` carries the shaped rows, the
  next cursor, and a per-row `source_event_id` hint = `transaction_id:line_item_seq`
  for ORDERS, else None (D33/D65 alignment).
- `preflight` is structural only and returns stable reason codes; it never propagates
  raw vendor or SDK error text (those can leak payload values).

### 4a. Stable preflight reason codes (closed set)

Mapped to `dis_audit.FailureCode`, canary-tested:

| reason code | meaning |
|-------------|---------|
| `AUTH_FAILED` | credentials rejected |
| `AUTH_EXPIRING` | credentials valid but near expiry (health hint) |
| `RATE_LIMITED` | vendor throttled the extract |
| `DISCOVERY_EMPTY` | no streams or entities available |
| `EXTRACT_EMPTY` | extract returned zero rows |
| `SCHEMA_UNRECOGNIZED` | vendor payload shape not mappable |
| `VENDOR_UNAVAILABLE` | vendor 5xx or network failure |

---

## 5. The one bronze.py change

Parameterize `dis_channel` on `BronzeRow`, defaulting to `"csv_upload"` so
csv-ingest-worker (which constructs `BronzeRow` without passing it) is byte-for-byte
unchanged; the connector passes `"api"`. `content_type` stays the hardcoded
`"text/csv"` (both channels land CSV). `find_prior` gains a `dis_channel` keyword
(default `DIS_CHANNEL`) because it filters on `dis_channel` in its WHERE clause; without
it a connector dedup lookup would filter on `csv_upload` and never match `api` rows,
breaking connector dedup and the D59 resume. Required for correctness.

A regression test proves the csv-ingest-worker bronze write and dedup query are
identical to today (both default to `csv_upload`).

---

## 6. ConnectorPipeline (mirrors csv pipeline.py, producer inversion)

Same stage discipline, same write-then-conditionally-publish ordering, same D59
idempotency and resume. The difference from the CSV pipeline: the connector is the
producer of the GCS object, so the CSV worker's read-a-pre-existing-object step is
replaced by extract, serialize, upload.

1. Read identity, `trace_id`, `connector_run_id` off the trigger (D54, hard rule 4).
2. Extract via the adapter (cursor incremental) for the requested domains.
3. Serialize to comma-delimited CSV bytes (header = template field keys).
4. sha256 over exactly the bytes to be uploaded.
5. Dedup: `find_prior(conn, upload_session_id=connector_run_id, payload_sha256=...,
   dis_channel="api")` under `rls_session` on the trigger tenant. Key
   (tenant, source_payload_id=connector_run_id, payload_sha256), 24h window,
   single-instance caveat D58. PUBLISHED or FAILED prior = full no-op returning the
   prior `trace_id`; unpublished RECEIVED = resume-and-mark (D59).
6. Preflight: structural, stable reason codes. Failure = FAILED bronze row + FAILURE
   audit, no publish, terminal (D5).
7. dis-pii gate over the CSV header, before the bronze write (hard rule 2). v1.0 has no
   backend, so any detected PII column raises.
8. Upload the CSV object to the bronze bucket (`build_object_path(ext="csv")` +
   `upload_bytes(content_type="text/csv")`). The connector is the producer.
9. `insert_row` (metadata only) via `rls_session`: `dis_channel="api"`,
   `source_payload_id=connector_run_id`,
   `original_filename="square:{stream}:{iso8601}"`, `row_count` from preflight,
   `template_id` and identity from the trigger.
10. Publish `ingress.ready` AFTER bronze lands (D5), `delimiter=","`, via the reused
    `IngressReadyEnvelope` and `Publisher`/`PubsubPublisher` seam; then `mark_published`.
11. connector_health seen and error emits, fire-and-forget (D116, hard rule 11).

All Postgres access via `dis-rls` `rls_session` on the trigger tenant (hard rules 1 and
12); the inherited `current_database()=='ithina_dis_db'` and NOBYPASSRLS guard applies.

### 6a. The publish seam

`csv_ingest_worker.publisher.build_ingress_ready(event, ...)` is typed to a
`CsvReceivedEvent`, whose `upload_session_id` is pattern-locked to `^us_[a-z0-9]{12}$`.
A connector trigger carries a `connector_run_id`, not a `us_` session id, so it cannot
build a valid `CsvReceivedEvent`, and editing `publisher.py` would break the one
bronze.py change rule. The ConnectorPipeline therefore reuses the `IngressReadyEnvelope`
model and the `Publisher`/`PubsubPublisher` seam directly and constructs the envelope
from the trigger fields (same model, same `to_bytes`, same topic, `delimiter=","`).
`build_ingress_ready` itself stays CSV-specific.

---

## 7. The trigger

A typed model (Pydantic, `extra="forbid"`, frozen) read at the start of a run. Carries,
never mints, the load-bearing identity:

```python
class ConnectorTrigger(BaseModel):
    schema_version: Literal[1]
    trace_id: UUID              # READ, never minted (hard rule 4)
    connector_run_id: str       # the dedup source_payload_id
    tenant_id: UUID             # trust boundary (D54)
    store_id: UUID
    source_id: str
    template_id: UUID
    domains: list[Domain]
    cursor: Cursor | None       # prior high-water mark for incremental extract
    tenant_display_code: str | None = None
    store_code: str | None = None
```

`connector_run_id` minting authority is the trigger producer (scheduler), not the
receiver. For the 24h dedup to collapse retries it must be stable across a retry of the
same logical run. The receiver only reads it.

---

## 8. Square adapter (`thalamus_square`), Square sandbox

Structured like csv-ingest-worker: `config` / `puller` / `preflight` / `pipeline` /
`main`, plus `auth`, `adapter`, `mapping`.

- OAuth per-tenant token from a config store; Locations to store resolution.
- Catalog (`ITEM` / `ITEM_VARIATION`) plus Inventory counts to
  `store_sku_current_position` CSV columns (snapshot template type).
- Orders line items to the sale-event path (sales template type), with the
  `source_event_id` hint = `transaction_id:line_item_seq`.

### 8a. CATALOG + INVENTORY to `store_sku_current_position`

| Square source | column | notes |
|---------------|--------|-------|
| variation id / SKU | `sku_id` | natural-key component |
| item name (+ variation) | `product_name` | |
| item description | `product_description` | |
| category | `product_category` | |
| variation `price_money` | `current_retail_price` | |
| GTIN / UPC | `barcode` | |
| inventory `quantity` | `stock_qty` | from the Inventory API |
| currency of `price_money` | `currency` | |
| store_code (from Location) | `store_code` | |
| (follow-up) | `tax_treatment` | NOT NULL, no direct Square source; see section 10 |

### 8b. ORDERS to the sale-event path (`StoreSkuSaleEvent`)

| Square source | column | notes |
|---------------|--------|-------|
| line-item catalog/variation id | `sku_id` | |
| order `created_at` / `closed_at` | `source_sale_timestamp` | |
| order id | `transaction_id` | |
| line-item index | `line_item_seq` | + order id -> source_event_id hint |
| line-item `quantity` | `quantity` | |
| line-item `base_price_money` | `unit_retail_price` | |
| line-item `total_money` / qty | `unit_sale_price` | |
| refund / void state | `event_subtype` | `SALE` / `RETURN` / `VOID` |
| discount total | `discount_amount` / `discount_pct` | |
| tax total | `tax_amount` | |
| tender type | `payment_method` | |
| currency | `currency` | |

The connector emits the source-shaped tabular rows a template maps; it never calls
`dis-mapping`.

---

## 9. import-linter contracts

Added to `dis/pyproject.toml`: `thalamus_square` and `thalamus_connector_sdk` are added
to `root_packages`, plus two `forbidden` contracts keeping each out of `dis_mapping`,
`dis_validation`, and `dis_enrichment`. Connectors are receivers; those pure pipeline
libs are the inherited downstream and must never be reached into from the receiver tier.

---

## 10. Completeness, prerequisites, follow-ups

### Completeness and enrichment (resolved, not a blocker)

`tax_treatment` and `currency` are enrichment-produced from `identity_mirror.stores`,
and dis-enrichment OVERWRITES the mapping value (D95, value wins). The hot completeness
gate (`streaming-consumer/pipeline/mapping.py` `HOT_REQUIRED_FROM_PROJECTION`) requires
only `{sku_id, product_name, current_retail_price}` from the mapping, all of which the
Square snapshot header supplies, so snapshot rows are `hot_complete`. The connector MUST
NOT emit `tax_treatment` (it would be discarded). A test guards that the snapshot header
covers the model-derived required set.

### Price-less variations (decision: drop with counted audit)

A Square variation with no `price_money` must not emit a blank `current_retail_price`.
Quarantine is NOT the low-cost option here: explicit connector-side quarantine is
off-lane (receivers write bronze only; quarantine is the consumer's Slice 11a lane), and
relying on the inherited quarantine is expensive because the consumer has no per-row
partial-success write (`orchestrate.py`: "ANY failed cell fails the chunk" and "the
chunk's GOOD rows are NOT written"), so one blank-price row withholds the whole snapshot
chunk's good rows from canonical. Therefore the connector DROPS price-less variations at
serialize time and records a counted, non-PII audit signal (`dropped_count` + a bounded
`dropped_sample` of `sku_id`s on the RECEIVED audit) plus the connector-health hint. Good
SKUs land; dropped ones are visible in audit. (INVENTORY-only rows carry no price by
design and are not dropped — they are the intentional partial-snapshot path.)

### Square onboarding prerequisite (four tables)

A Square customer onboards only when all of the following exist:
1. `identity_mirror.tenants` + `identity_mirror.stores` (Mirror Sync from Customer
   Master), with the store carrying `currency` + `tax_treatment` (both NOT NULL there;
   the enrichment source of truth).
2. `config.sources` row for the source, `channel='api'`.
3. An ACTIVE `config.source_mappings` row, `template_type='snapshot'`, mapping the CSV
   header to `{sku_id, product_name, current_retail_price, ...}`.
4. `telemetry.connector_health` is worker-emitted per run (no pre-provisioning).

### Other follow-ups

- Extracting `bronze.py` and `publisher.py` into a shared `dis-bronze` lib (noted debt).
- The trigger producer (scheduler) and cursor persistence store are the orchestrator's
  concern; the receiver only consumes triggers.
- RETURN/VOID discrimination and precise Square money semantics are mapping refinements
  (v1 maps order line items as SALE, pre-tax amounts).

---

## 11. Testing and guardrails

- Tests ship in the same commit as code.
- Required tests: no-`dis_core.identity`-import (and trace mint explodes); dedup-window
  plus D59 resume; preflight-stable-codes; and the csv-ingest-worker
  bronze-default-channel regression.
- Square: catalog/inventory to current_position CSV columns; orders to sale-event
  columns with the source_event_id hint.
- `mypy --strict` per-package gate and import-linter contracts must pass; both packages
  join the gate lists in the same commit that clears them.
- No em-dashes anywhere. No commit; operator reviews the diff first.
