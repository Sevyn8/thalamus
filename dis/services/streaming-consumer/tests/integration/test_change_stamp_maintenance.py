"""Per-attribute change-stamp maintenance on the catalogue upsert.

Proven by writing REAL rows to ithina_dis_db (5433) through the real pipeline (the
seeded ``template_type='snapshot'`` mapping) and reading them back after each
ingestion — never a mock, never an SQL-string assertion. The conftest raises
StackRequiredError when the stack is absent (ERROR-not-skip).

The two stamps — ``current_retail_price_changed_at`` / ``product_name_changed_at``
— must advance to the ingest time (the catalogue path's ``received_ts``, the same
clock the event-time gate uses) ONLY when their watched value actually changes, and
HOLD when it is re-ingested unchanged; an older-ingest-time snapshot advances
nothing and leaves the whole row untouched.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from dis_testing.fixtures import PRIMARY_TENANT

from .conftest import BASE_TS, CATALOGUE_SOURCE_ID, Cleanup, catalogue_csv, seed_chunk

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from dis_storage.client import StorageClient
    from streaming_consumer.orchestrate import ConsumerPipeline

pytestmark = pytest.mark.integration

_READ_SQL = text(
    "SELECT product_name, current_retail_price, product_category, unit_cost, stock_qty, "
    "last_source_event_at, last_updated_at, attribute_staleness_map, "
    "current_retail_price_changed_at, product_name_changed_at "
    "FROM canonical.store_sku_current_position "
    "WHERE tenant_id = CAST(:tenant AS uuid) AND sku_id = :sku"
)


def _unique_sku(prefix: str) -> str:
    from dis_core.ids import new_uuid7

    return f"{prefix}-{new_uuid7().hex[:10]}"


def _read(dis_admin: Engine, sku: str) -> Any:
    with dis_admin.begin() as conn:
        return conn.execute(_READ_SQL, {"tenant": str(PRIMARY_TENANT.uuid), "sku": sku}).one()


def _row_count(dis_admin: Engine, sku: str) -> int:
    with dis_admin.begin() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT count(*) FROM canonical.store_sku_current_position "
                    "WHERE tenant_id = CAST(:tenant AS uuid) AND sku_id = :sku"
                ),
                {"tenant": str(PRIMARY_TENANT.uuid), "sku": sku},
            ).scalar_one()
        )


async def _ingest(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    *,
    sku: str,
    name: str,
    category: str,
    price: str,
    cost: str,
    qty: str,
    received_ts: datetime,
    expected_hot: int = 1,
    expected_noops: int = 0,
) -> None:
    """One catalogue snapshot ingestion for ``sku`` through the real pipeline.

    ``expected_hot`` / ``expected_noops`` are EXACT: a forward write is 1/0; the
    gate-rejected older replay (Ingestion 5) is 0/1. The no-op still ACKs (disposition ``written``).
    """
    chunk = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=catalogue_csv([(sku, name, category, price, cost, qty)]),
        source_id=CATALOGUE_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
        received_ts=received_ts,
    )
    outcome = await pipeline.process(chunk.event)
    # Routing/completeness unchanged: the catalogue COMPLETE path, hot-only, one row.
    assert outcome.disposition == "written"  # a no-op-older still acks
    assert outcome.report is not None
    assert outcome.report.event_rows_written == 0
    assert outcome.report.hot_rows_upserted == expected_hot
    assert outcome.report.hot_noops == expected_noops
    assert outcome.report.written_to_table == "canonical.store_sku_current_position"


async def test_change_stamps_advance_only_on_real_change(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
) -> None:
    """The sequenced acceptance scenario (AC1-AC5), each assertion read from the DB."""
    sku = _unique_sku("STAMP")
    cleanup.skus.append(sku)

    t1 = BASE_TS
    t2 = BASE_TS + timedelta(minutes=1)
    t3 = BASE_TS + timedelta(minutes=2)
    t4 = BASE_TS + timedelta(minutes=3)
    t5 = BASE_TS - timedelta(minutes=5)  # strictly older than the stored t4

    # --- Ingestion 1: true INSERT arm (no prior row). Both stamps set (AC1). -----
    assert _row_count(dis_admin, sku) == 0  # confirms this hits the INSERT arm, not a DO UPDATE
    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        category="Hardware",
        price="9.99",
        cost="4.00",
        qty="42",
        received_ts=t1,
    )
    r1 = _read(dis_admin, sku)
    assert r1.current_retail_price_changed_at == t1
    assert r1.product_name_changed_at == t1

    # --- Ingestion 2: change ONLY name. Name advances, price HOLDS (AC3). --------
    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget-v2",
        category="Hardware",
        price="9.99",
        cost="4.00",
        qty="42",
        received_ts=t2,
    )
    r2 = _read(dis_admin, sku)
    assert r2.product_name == "Widget-v2"  # value overwrite intact
    assert r2.product_name_changed_at == t2  # advanced
    assert r2.current_retail_price_changed_at == t1  # held (unchanged value)

    # --- Ingestion 3: change ONLY price. Price advances, name HOLDS (AC2/AC3). ---
    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget-v2",
        category="Hardware",
        price="12.50",
        cost="4.00",
        qty="42",
        received_ts=t3,
    )
    r3 = _read(dis_admin, sku)
    assert r3.current_retail_price == Decimal("12.5000")  # value overwrite intact
    assert r3.current_retail_price_changed_at == t3  # advanced
    assert r3.product_name_changed_at == t2  # held

    # --- Ingestion 4: change ONLY a non-watched column. Neither advances (AC4). --
    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget-v2",
        category="Softlines",
        price="12.50",
        cost="4.00",
        qty="42",
        received_ts=t4,
    )
    r4 = _read(dis_admin, sku)
    assert r4.product_category == "Softlines"  # non-watched value overwrite intact
    assert r4.current_retail_price_changed_at == t3  # held
    assert r4.product_name_changed_at == t2  # held

    # Row-touch timestamp advances on every APPLIED write (trigger unaffected).
    assert r1.last_updated_at < r2.last_updated_at < r3.last_updated_at < r4.last_updated_at

    # --- Ingestion 5: older-ingest-time replay. Nothing advances; row unchanged (AC5). --
    # The rejected replay is counted as a no-op (0 hot / 1 noop), NOT a write.
    # Exact counts — pre-fix the catalogue path reported 1/0, so these would go red without Fix 2.
    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="REPLAY-OLD",
        category="Perishables",
        price="1.00",
        cost="9.99",
        qty="1",
        received_ts=t5,
        expected_hot=0,
        expected_noops=1,
    )
    r5 = _read(dis_admin, sku)
    # The event-time gate blocked the whole DO UPDATE: every column equals post-ingestion-4.
    assert r5.product_name == r4.product_name
    assert r5.current_retail_price == r4.current_retail_price
    assert r5.product_category == r4.product_category
    assert r5.unit_cost == r4.unit_cost
    assert r5.stock_qty == r4.stock_qty
    assert r5.last_source_event_at == r4.last_source_event_at
    assert r5.last_updated_at == r4.last_updated_at  # no UPDATE fired → trigger did not touch it
    assert r5.current_retail_price_changed_at == r4.current_retail_price_changed_at
    assert r5.product_name_changed_at == r4.product_name_changed_at

    # Staleness map unchanged by this slice: the new stamps never enter it.
    assert "current_retail_price_changed_at" not in r4.attribute_staleness_map
    assert "product_name_changed_at" not in r4.attribute_staleness_map


async def test_conditional_stamp_is_load_bearing(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: prove the IS DISTINCT FROM CASE — not luck — holds the stamp.

    Swap ONLY the stamp clause for an UNCONDITIONAL variant (advance on every
    update), run the real pipeline, re-ingest IDENTICAL values, and show the stamp
    ADVANCES — i.e. the ingestion-2/4 hold assertions above would FAIL under the
    exact mistake the CASE guards against. Mirrors the mis-classification
    guard in test_write_gate_derivation.py.
    """
    import streaming_consumer.sinks.canonical as canonical

    monkeypatch.setattr(
        canonical,
        "_stamp_set_clause",
        lambda value_col, stamp_col: f"{stamp_col} = EXCLUDED.{stamp_col}",
    )

    sku = _unique_sku("STAMPNEG")
    cleanup.skus.append(sku)
    t1 = BASE_TS
    t2 = BASE_TS + timedelta(minutes=1)
    t3 = BASE_TS + timedelta(minutes=2)

    # Insert, then re-ingest the SAME watched values at a later ingest time.
    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        category="Hardware",
        price="9.99",
        cost="4.00",
        qty="42",
        received_ts=t1,
    )
    r1 = _read(dis_admin, sku)
    assert r1.current_retail_price_changed_at == t1
    assert r1.product_name_changed_at == t1

    # (a) AC2 shape — identical re-ingest (nothing changes). Under the unconditional
    # clause BOTH stamps advance, so the real code's AC2 hold is CASE-dependent.
    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        category="Hardware",
        price="9.99",
        cost="4.00",
        qty="42",
        received_ts=t2,
    )
    r2 = _read(dis_admin, sku)
    assert r2.current_retail_price_changed_at == t2
    assert r2.product_name_changed_at == t2
    assert r2.current_retail_price_changed_at != r1.current_retail_price_changed_at
    assert r2.product_name_changed_at != r1.product_name_changed_at

    # (b) AC4 shape — change ONLY a non-watched column (category); price + name are
    # unchanged. Under the unconditional clause BOTH stamps STILL advance, so the
    # real code's AC4 hold is ALSO CASE-dependent (not only AC2's). This is the case
    # the plan's negative control previously did not exercise.
    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        category="Softlines",
        price="9.99",
        cost="4.00",
        qty="42",
        received_ts=t3,
    )
    r3 = _read(dis_admin, sku)
    assert r3.product_category == "Softlines"  # the non-watched change did land
    assert r3.current_retail_price_changed_at == t3  # would-be-held stamp advanced under the mistake
    assert r3.product_name_changed_at == t3


async def test_equal_received_ts_replay_holds_stamps(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
) -> None:
    """Replay-safety edge the ``>=`` gate creates: an identical re-ingest at the SAME
    received_ts RE-ENTERS the DO UPDATE arm (gate is ``>=``, so equal passes), yet the
    IS DISTINCT FROM CASE sees equal values and HOLDS both stamps — and the row is not
    corrupted. Proven by showing the row-touch timestamp advances (the DO UPDATE fired)
    while the two stamps do not.
    """
    sku = _unique_sku("STAMPEQ")
    cleanup.skus.append(sku)
    t1 = BASE_TS

    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        category="Hardware",
        price="9.99",
        cost="4.00",
        qty="42",
        received_ts=t1,
    )
    r1 = _read(dis_admin, sku)
    assert r1.current_retail_price_changed_at == t1
    assert r1.product_name_changed_at == t1

    # Identical re-ingest at the EXACT same received_ts (not older, not newer).
    await _ingest(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        category="Hardware",
        price="9.99",
        cost="4.00",
        qty="42",
        received_ts=t1,
    )
    r2 = _read(dis_admin, sku)

    # The DO UPDATE re-entered (equal time passes the >= gate): row-touch advanced...
    assert r2.last_updated_at > r1.last_updated_at
    assert r2.last_source_event_at == r1.last_source_event_at  # equal time, unchanged
    # ...but both stamps HELD (values equal → IS DISTINCT FROM false), and no corruption.
    assert r2.current_retail_price_changed_at == t1
    assert r2.product_name_changed_at == t1
    assert r2.product_name == r1.product_name
    assert r2.current_retail_price == r1.current_retail_price


async def test_multi_row_chunk_stamps_are_per_row(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
) -> None:
    """A single catalogue chunk carrying two SKUs upserts each row via its own
    per-group execute (canonical.py write_catalogue_chunk loop), so the stamp binds
    must not cross-assign between rows. Change ONLY SKU-A's price on a second chunk
    and confirm A's price stamp advances while A's name stamp and BOTH of B's stamps
    hold — and B's value is untouched.
    """
    a = _unique_sku("MULTI-A")
    b = _unique_sku("MULTI-B")
    cleanup.skus.extend([a, b])
    t1 = BASE_TS
    t2 = BASE_TS + timedelta(minutes=1)

    # One chunk, two rows.
    chunk1 = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=catalogue_csv(
            [
                (a, "A-name", "Hardware", "1.00", "0.50", "5"),
                (b, "B-name", "Hardware", "2.00", "0.60", "6"),
            ]
        ),
        source_id=CATALOGUE_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
        received_ts=t1,
    )
    outcome1 = await pipeline.process(chunk1.event)
    assert outcome1.report is not None
    assert outcome1.report.hot_rows_upserted == 2  # both rows in the one chunk
    ra1, rb1 = _read(dis_admin, a), _read(dis_admin, b)
    assert ra1.current_retail_price_changed_at == t1 and ra1.product_name_changed_at == t1
    assert rb1.current_retail_price_changed_at == t1 and rb1.product_name_changed_at == t1

    # Second chunk: change ONLY A's price; B carried unchanged.
    chunk2 = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=catalogue_csv(
            [
                (a, "A-name", "Hardware", "9.99", "0.50", "5"),
                (b, "B-name", "Hardware", "2.00", "0.60", "6"),
            ]
        ),
        source_id=CATALOGUE_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
        received_ts=t2,
    )
    await pipeline.process(chunk2.event)
    ra2, rb2 = _read(dis_admin, a), _read(dis_admin, b)

    # A: price stamp advanced, name stamp held. No cross-assignment to B.
    assert ra2.current_retail_price == Decimal("9.9900")
    assert ra2.current_retail_price_changed_at == t2
    assert ra2.product_name_changed_at == t1
    # B: both stamps held and value untouched.
    assert rb2.current_retail_price_changed_at == t1
    assert rb2.product_name_changed_at == t1
    assert rb2.current_retail_price == rb1.current_retail_price
