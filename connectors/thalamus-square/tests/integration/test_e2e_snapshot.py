"""E2E spine (offline), on the live stack: provision -> offline Square pull -> the inherited
streaming-consumer pipeline -> canonical.store_sku_current_position for W-001.

Proves the manually-demonstrated spine as a durable test:
- provisioning.py registers the api source + an ACTIVE snapshot template;
- the transport mints a producer-owned connector_run_id (no wall-clock) and runs one offline
  pull via a fake SquareApi (canned PLN catalog+inventory);
- the inherited ConsumerPipeline (unchanged) fetches the connector's bronze CSV, maps,
  validates, enriches, and writes canonical;
- exactly 2 rows land for the store, currency=PLN + tax_treatment=INCLUSIVE (enrichment) and
  dis_channel=api;
- dedup: same run-key => duplicate_noop, no new bronze, canonical unchanged; a new run-key =>
  a new bronze row and a canonical upsert (still 2 rows, refreshed).

The test sweeps everything it could create - keyed by (tenant_id, source_id), not by a
captured id, so a re-run over provisioning's idempotent path is also cleaned - in a finally,
returning the shared DB to baseline. FK-safe order matters: every table that references
config.source_mappings via mapping_version_id (canonical/staging snapshot + sale + change
events, quarantined_rows) is cleared before the source_mappings row, else its DELETE FK-fails
and the whole cleanup rolls back. The receiver reads connector_run_id off the trigger and mints
none; only the transport derives it.
"""

from __future__ import annotations

import os
from datetime import datetime
from typing import Any
from uuid import UUID

import pytest
import sqlalchemy as sa
from sqlalchemy import Engine

from dis_audit import AuditBackend, select_writer
from dis_core.timestamps import ensure_utc
from dis_core.trace_id import new_trace_id
from dis_quarantine import PostgresQuarantineWriter
from dis_rls import create_rls_engine
from dis_storage import StorageClient
from streaming_consumer.envelope import IngressReadyEvent  # type: ignore[import-untyped]
from streaming_consumer.orchestrate import (  # type: ignore[import-untyped]
    ConsumeOutcome,
    ConsumerPipeline,
)
from streaming_consumer.sinks.audit import ConsumerAudit  # type: ignore[import-untyped]
from streaming_consumer.sinks.quarantine import ConsumerQuarantine  # type: ignore[import-untyped]
from thalamus_connector_sdk import ConnectorOutcome, SdkConfig
from thalamus_connector_sdk.adapter import Domain
from thalamus_connector_sdk.trigger import ConnectorTrigger
from thalamus_square.config import SquareConfig
from thalamus_square.fakes import FakeSquareApi, FakeTokenStore
from thalamus_square.main import run_trigger
from thalamus_square.pipeline import build_engine, build_square_pipeline
from thalamus_square.provisioning import provision
from thalamus_square.run_id import mint_connector_run_id

pytestmark = pytest.mark.integration

_TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
_STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
_STORE_CODE = "W-001"
_SOURCE = "square_pos_v2"
_SKUS = {"ZAB-COFFEE-250", "ZAB-CHIPS-100"}


def _require_env(name: str) -> str:
    """Fail loud when the stack env is absent (no silent skip; matches the DIS posture)."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set: the spine E2E needs the local stack (make run-local + .env)")
    return value


def _admin_engine() -> Engine:
    """A synchronous RLS-bypass engine for reads + cleanup (POSTGRES_ADMIN_URL, else the user URL)."""
    url = os.environ.get("POSTGRES_ADMIN_URL") or _require_env("POSTGRES_URL")
    return sa.create_engine(url)


def _bronze_meta(admin: Engine, bronze_id: UUID) -> tuple[str, datetime]:
    with admin.begin() as conn:
        row = conn.execute(
            sa.text("SELECT gcs_uri, received_at FROM bronze.data_ingress_events WHERE id = :b"),
            {"b": str(bronze_id)},
        ).one()
    return str(row.gcs_uri), row.received_at


def _canonical_rows(admin: Engine) -> list[dict[str, Any]]:
    with admin.begin() as conn:
        rows = (
            conn.execute(
                sa.text(
                    "SELECT sku_id, current_retail_price, currency, tax_treatment, stock_qty, "
                    "       dis_channel, trace_id "
                    "FROM canonical.store_sku_current_position "
                    "WHERE tenant_id = CAST(:t AS uuid) AND store_id = CAST(:s AS uuid) ORDER BY sku_id"
                ),
                {"t": str(_TENANT), "s": str(_STORE)},
            )
            .mappings()
            .all()
        )
    return [dict(r) for r in rows]


def _bronze_count(admin: Engine) -> int:
    with admin.begin() as conn:
        return int(
            conn.execute(
                sa.text("SELECT count(*) FROM bronze.data_ingress_events WHERE source_id = :s"),
                {"s": _SOURCE},
            ).scalar_one()
        )


async def _run_pull(template_id: UUID, *, run_key: str) -> tuple[str, UUID, ConnectorOutcome]:
    """Run one offline pull through the transport seam; returns (run_id, trace_id, outcome)."""
    sdk_config = SdkConfig.from_env()
    square_config = SquareConfig.from_env()
    run_id = mint_connector_run_id(str(_TENANT), str(_STORE), _SOURCE, str(template_id), run_key)
    trace_id = new_trace_id()
    trigger = ConnectorTrigger(
        schema_version=1,
        trace_id=trace_id,
        connector_run_id=run_id,
        tenant_id=_TENANT,
        store_id=_STORE,
        source_id=_SOURCE,
        template_id=template_id,
        domains=[Domain.CATALOG],
        cursor=None,
        store_code=_STORE_CODE,
    )
    engine = build_engine(sdk_config)
    try:
        pipeline = build_square_pipeline(
            sdk_config, square_config, engine=engine, token_store=FakeTokenStore(), api=FakeSquareApi()
        )
        outcome = await run_trigger(pipeline, trigger)
    finally:
        await engine.dispose()
    return run_id, trace_id, outcome


async def _drive_consumer(
    admin: Engine, *, bronze_id: UUID, trace_id: UUID, template_id: UUID
) -> ConsumeOutcome:
    """Drive the inherited ConsumerPipeline in-process on the connector's ingress.ready.

    The event is rebuilt from the connector's own bronze row (gcs_uri + received_at), so the
    consumer's fetch cross-check (event vs bronze) is a built-in consistency guard.
    """
    gcs_uri, received_at = _bronze_meta(admin, bronze_id)
    event = IngressReadyEvent(
        schema_version=1,
        trace_id=trace_id,
        tenant_id=_TENANT,
        store_id=_STORE,
        source_id=_SOURCE,
        template_id=template_id,
        bronze_ref=bronze_id,
        gcs_uri=gcs_uri,
        received_ts=ensure_utc(received_at),
        delimiter=",",
    )
    bucket = SdkConfig.from_env().bronze_bucket
    engine = create_rls_engine(_require_env("POSTGRES_URL"))
    try:
        pipeline = ConsumerPipeline(
            engine=engine,
            storage=StorageClient(bucket=bucket),
            audit=ConsumerAudit(select_writer(AuditBackend.POSTGRES, engine=engine)),
            quarantine=ConsumerQuarantine(PostgresQuarantineWriter(engine)),
            bronze_bucket=bucket,
        )
        return await pipeline.process(event)
    finally:
        await engine.dispose()


# Tables that reference config.source_mappings via mapping_version_id (FK). EVERY one must be
# cleared before the source_mappings row, or its DELETE raises a FK violation, the single
# cleanup transaction rolls back, and the source_mappings row is left as residue. canonical.
# store_sku_current_position is the only one the happy path writes, but an
# intermittently quarantined / staged row also holds a reference, so all seven are swept.
_MAPPING_VERSION_CHILDREN: tuple[str, ...] = (
    "canonical.store_sku_current_position",
    "canonical.store_sku_sale_events",
    "canonical.store_sku_change_events",
    "staging.store_sku_current_position",
    "staging.store_sku_sale_events",
    "staging.store_sku_change_events",
    "quarantine.quarantined_rows",
)


def _cleanup(admin: Engine) -> None:
    """Return the shared DB to baseline, keyed by (tenant_id, source_id) - NOT by any
    id this run captured. Provisioning is idempotent (ON CONFLICT / the ACTIVE-exists guard),
    so on a re-run it can hit a PRE-EXISTING row it never created; deleting by a captured
    template_id/trace would miss it. Keying by (tenant, source) sweeps the row whether or not
    THIS run wrote it.

    FK-safe order is load-bearing: clear every mapping_version_id child (canonical/staging
    snapshot + sale + change events, and quarantined_rows) BEFORE config.source_mappings, then
    bronze, connector_health, source_mappings, sources. audit.events has no FK back to bronze
    or source_mappings, so it is scoped by the trace_id of this source's bronze events (plus
    this mapping) and deleted first (re-run safe, no captured trace list).
    """
    params = {"t": str(_TENANT), "s": _SOURCE}
    mv_scope = (
        "mapping_version_id IN (SELECT mapping_version_id FROM config.source_mappings "
        "WHERE tenant_id = CAST(:t AS uuid) AND source_id = :s)"
    )
    with admin.begin() as conn:
        # RLS scope for the NOBYPASSRLS fallback (admin_url unset -> the user URL). A superuser
        # POSTGRES_ADMIN_URL ignores these; harmless either way.
        conn.execute(sa.text("SELECT set_config('app.user_type', 'TENANT', true)"))
        conn.execute(sa.text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(_TENANT)})

        # audit.events has no source_id and no FK back to bronze/source_mappings, so it is
        # scoped three ways (all keyed off this source, never a captured id), covering every
        # audit shape this test emits:
        #   * trace_id in this source's bronze traces -> the RECEIVED / PII_TOKENIZED events,
        #     which carry a null data_ingress_event_id but share the pull's trace;
        #   * data_ingress_event_id in this source's bronze -> the DUPLICATE_NOOP event, whose
        #     own trace never wrote bronze but which points at the PRIOR bronze row it deduped;
        #   * mapping_version_id in this mapping -> the consumer's canonical-write events.
        # Runs before bronze / source_mappings are deleted so all three subqueries still resolve.
        conn.execute(
            sa.text(
                "DELETE FROM audit.events "
                "WHERE trace_id IN (SELECT trace_id FROM bronze.data_ingress_events WHERE source_id = :s) "
                "OR data_ingress_event_id IN "
                "  (SELECT id FROM bronze.data_ingress_events WHERE source_id = :s) "
                f"OR {mv_scope}"
            ),
            params,
        )
        for table in _MAPPING_VERSION_CHILDREN:
            conn.execute(sa.text(f"DELETE FROM {table} WHERE {mv_scope}"), params)

        conn.execute(sa.text("DELETE FROM bronze.data_ingress_events WHERE source_id = :s"), params)
        conn.execute(
            sa.text(
                "DELETE FROM telemetry.connector_health WHERE tenant_id = CAST(:t AS uuid) AND source_id = :s"
            ),
            params,
        )
        conn.execute(
            sa.text(
                "DELETE FROM config.source_mappings WHERE tenant_id = CAST(:t AS uuid) AND source_id = :s"
            ),
            params,
        )
        conn.execute(
            sa.text("DELETE FROM config.sources WHERE tenant_id = CAST(:t AS uuid) AND source_id = :s"),
            params,
        )


def _drain_ingress_ready() -> None:
    """Best-effort: pull+ack the connector's published ingress.ready messages so they do not
    linger on the shared subscription (test hygiene; DB residue is handled by _cleanup)."""
    try:
        # attr-defined: google-cloud-secret-manager (square-oauth, S2) ships py.typed and
        # makes google.cloud a resolved namespace in this package's mypy run, so the untyped
        # sibling pubsub_v1 no longer resolves as an attribute. Runtime import is unaffected.
        from google.cloud import pubsub_v1  # type: ignore[attr-defined]

        project = _require_env("PUBSUB_PROJECT_ID")
        sub = pubsub_v1.SubscriberClient()
        path = sub.subscription_path(project, "streaming-consumer.ingress.ready")
        resp = sub.pull(request={"subscription": path, "max_messages": 50, "return_immediately": True})
        ack_ids = [m.ack_id for m in resp.received_messages]
        if ack_ids:
            sub.acknowledge(request={"subscription": path, "ack_ids": ack_ids})
    except Exception:  # noqa: BLE001 - hygiene only, never fails the test
        pass


async def test_spine_offline_pull_lands_canonical_for_w001_and_dedups() -> None:
    _require_env("POSTGRES_URL")
    admin = _admin_engine()
    try:
        # provision INSIDE the try so the finally sweeps its writes even if it partially
        # succeeds (source registered) before a later step raises.
        provisioned = provision(
            url=_require_env("POSTGRES_URL"), tenant_id=_TENANT, store_code=_STORE_CODE, source_id=_SOURCE
        )
        template_id = provisioned.template_id
        # --- bootstrap run: offline pull -> inherited pipeline -> canonical ---
        boot_run_id, boot_trace, boot_out = await _run_pull(template_id, run_key="e2e-bootstrap")
        assert boot_out.disposition == "ingested"
        assert boot_out.bronze_id is not None
        consume = await _drive_consumer(
            admin, bronze_id=boot_out.bronze_id, trace_id=boot_trace, template_id=template_id
        )
        assert consume.disposition == "written"

        rows = _canonical_rows(admin)
        assert len(rows) == 2
        assert {r["sku_id"] for r in rows} == _SKUS
        for r in rows:
            assert r["currency"] == "PLN"  # enrichment-supplied, store-owned
            assert r["tax_treatment"] == "INCLUSIVE"  # enrichment-supplied
            assert r["dis_channel"] == "api"
        assert _bronze_count(admin) == 1

        # --- dedup: SAME run-key => duplicate_noop, no new bronze, canonical unchanged ---
        same_run_id, same_trace, same_out = await _run_pull(template_id, run_key="e2e-bootstrap")
        assert same_run_id == boot_run_id  # stable id, no wall-clock
        assert same_out.disposition == "duplicate_noop"
        assert _bronze_count(admin) == 1  # no second bronze row
        assert len(_canonical_rows(admin)) == 2

        # --- new intended run: NEW run-key => not deduped (new bronze), canonical upserts ---
        new_run_id, new_trace, new_out = await _run_pull(template_id, run_key="e2e-refresh")
        assert new_run_id != boot_run_id
        assert new_out.disposition == "ingested"
        assert new_out.bronze_id is not None
        assert _bronze_count(admin) == 2  # a second bronze row: not deduped away
        refresh_consume = await _drive_consumer(
            admin, bronze_id=new_out.bronze_id, trace_id=new_trace, template_id=template_id
        )
        assert refresh_consume.disposition == "written"

        refreshed = _canonical_rows(admin)
        assert len(refreshed) == 2  # same SKUs upserted in place (natural-key), not duplicated
        assert all(str(r["trace_id"]) == str(new_trace) for r in refreshed)  # the refresh wrote them
    finally:
        _cleanup(admin)
        _drain_ingress_ready()
        admin.dispose()
