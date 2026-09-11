"""Per-column MERGE of ``attribute_staleness_map`` on the catalogue upsert.

Proven by writing REAL rows to ithina_dis_db (5433) through the real pipeline and
reading the persisted map back after each ingestion — never a mock, never an
SQL-string assertion. The conftest raises StackRequiredError when the stack is absent
(ERROR-not-skip).

The map is WRITE-PRESENCE based (a carried column's key advances to the write's
``received_ts`` even when its value is unchanged — the opposite of the 50b
``*_changed_at`` value-change stamps) and MERGED per-column (a write updates only the
keys it carries and preserves every other stored key; a never-carried column has no
key). The merge is demonstrated by crossing two seeded snapshot mappings on ONE SKU:
the full catalogue mapping carries price+cost+qty, the minimal mapping carries
price+qty (it does NOT rename cost → it omits ``unit_cost``), so the second write drops
a tracked column the first set.

Tracked set: current_retail_price, unit_cost, stock_qty,
expiry_date. Not tracked: currency, product_name, sku_status,
promo_identifier. ``expiry_date`` is covered here only as the "never carried → no key"
case (its positive stamp needs the expiry CHECK triple — a named deferral).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text

from dis_testing.fixtures import PRIMARY_TENANT

from .conftest import (
    BASE_TS,
    CATALOGUE_MINIMAL_SOURCE_ID,
    CATALOGUE_SOURCE_ID,
    Cleanup,
    catalogue_csv,
    catalogue_minimal_csv,
    seed_chunk,
    seed_hot_row,
)

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from dis_storage.client import StorageClient
    from streaming_consumer.orchestrate import ConsumerPipeline

pytestmark = pytest.mark.integration

# Columns not in the tracked set — must NEVER be keys in the map.
_REMOVED = {"currency", "product_name", "sku_status", "promo_identifier"}

_READ_SQL = text(
    "SELECT attribute_staleness_map, current_retail_price, unit_cost, stock_qty, "
    "product_name, currency, mapping_version_id, last_source_event_at, last_updated_at, "
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


async def _ingest_full(
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
    """Full catalogue snapshot (carries price+cost+qty → tracked {price, unit_cost, qty}).

    ``expected_hot`` / ``expected_noops`` are EXACT: a forward write is 1/0; a
    gate-rejected older write is 0/1. The no-op still ACKs (disposition ``written``) — the fix
    lives only in the count fields, not the ack/nack disposition.
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
    assert outcome.disposition == "written"  # a no-op-older still acks (successful no-op)
    assert outcome.report is not None
    assert outcome.report.event_rows_written == 0  # hot-only, unchanged
    assert outcome.report.hot_rows_upserted == expected_hot
    assert outcome.report.hot_noops == expected_noops


async def _ingest_minimal(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    *,
    sku: str,
    name: str,
    price: str,
    qty: str,
    received_ts: datetime,
) -> None:
    """Minimal snapshot (carries price+qty, NO cost → tracked {price, qty}; drops unit_cost)."""
    chunk = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=catalogue_minimal_csv([(sku, name, price, qty)]),
        source_id=CATALOGUE_MINIMAL_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
        received_ts=received_ts,
    )
    outcome = await pipeline.process(chunk.event)
    assert outcome.disposition == "written"
    assert outcome.report is not None
    assert outcome.report.event_rows_written == 0
    assert outcome.report.hot_rows_upserted == 1


async def test_staleness_map_merges_per_column(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    consumer_mappings: dict[str, int],
) -> None:
    """The full acceptance sequence (AC1-AC5), each assertion read from the DB."""
    sku = _unique_sku("MERGE")
    cleanup.skus.append(sku)
    t1 = BASE_TS
    t2 = BASE_TS + timedelta(minutes=1)

    # --- Write 1: full catalogue @ t1. INSERT arm builds the map plainly. ----------
    assert _row_count(dis_admin, sku) == 0  # confirms this hits the INSERT arm
    await _ingest_full(
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
    m1 = r1.attribute_staleness_map
    # AC1 (present columns stamped to received_ts): the three tracked columns the row set.
    assert set(m1) == {"current_retail_price", "unit_cost", "stock_qty"}
    assert set(m1.values()) == {t1.isoformat()}
    # AC3 (never carried → no key): expiry_date is in no seeded mapping.
    assert "expiry_date" not in m1
    # AC5 (removed columns gone): even though product_name/currency ARE written as values.
    assert _REMOVED.isdisjoint(m1)

    # --- Write 2: minimal @ t2, SAME price value (9.99), drops cost. ---------------
    await _ingest_minimal(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        price="9.99",
        qty="42",
        received_ts=t2,
    )
    r2 = _read(dis_admin, sku)
    m2 = r2.attribute_staleness_map

    # AC1: the carried columns advanced to t2.
    assert m2["current_retail_price"] == t2.isoformat()
    assert m2["stock_qty"] == t2.isoformat()
    # AC4 (write-presence, not value-change): price was carried with the IDENTICAL value
    # 9.99, yet its stamp advanced t1 -> t2 (a refresh, not a change).
    assert r2.current_retail_price == Decimal("9.9900")  # value unchanged
    assert m1["current_retail_price"] == t1.isoformat()  # was t1 before write 2
    assert m2["current_retail_price"] == t2.isoformat()  # advanced despite equal value
    # AC2 (merge, not wipe): unit_cost was NOT carried by the minimal write, so its key
    # is PRESERVED at its prior t1 timestamp — the core merge behavior.
    assert m2["unit_cost"] == t1.isoformat()
    # AC3 / AC5 still hold after the merge.
    assert "expiry_date" not in m2
    assert _REMOVED.isdisjoint(m2)
    # The map is exactly the merged three keys — no key was dropped by the narrower write.
    assert set(m2) == {"current_retail_price", "unit_cost", "stock_qty"}

    # --- Regression: value columns, lineage, 50b stamps unchanged by the map rework. -
    assert r2.unit_cost == Decimal("4.0000")  # minimal did not carry cost → value held
    assert r2.stock_qty == Decimal("42.000")
    assert r2.product_name == "Widget"
    assert r2.mapping_version_id == consumer_mappings[CATALOGUE_MINIMAL_SOURCE_ID]  # latest write
    assert r2.last_source_event_at == t2  # event-time advanced
    assert r2.last_updated_at > r1.last_updated_at  # trigger fired on the applied update
    # 50b change-stamps: price value unchanged (9.99 -> 9.99) and name unchanged, so both
    # HOLD at t1 — the write-presence map advancing price does NOT touch the value-change
    # stamps (the two mechanisms stay separate).
    assert r2.current_retail_price_changed_at == t1
    assert r2.product_name_changed_at == t1
    # And the 50b stamp columns are never keys in the map.
    assert "current_retail_price_changed_at" not in m2
    assert "product_name_changed_at" not in m2


async def test_merge_into_null_stored_map_does_not_wipe(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    consumer_mappings: dict[str, int],
) -> None:
    """R1 (COALESCE guard, the single most dangerous edge): a row whose
    ``attribute_staleness_map`` is NULL before a catalogue merge must NOT be wiped to NULL
    by ``NULL || X``. ``seed_hot_row`` inserts a row that never sets the map (NULL) and no
    ``last_source_event_at`` (NULL), so the catalogue write takes the DO UPDATE arm (the
    event-time gate passes on ``last_source_event_at IS NULL``) and
    ``COALESCE(NULL, '{}'::jsonb) || <built map>`` must yield exactly the carried keys.

    The W1-always-INSERT merge sequence in ``test_staleness_map_merges_per_column`` never
    exercises this arm — this is the coverage that catches a missing COALESCE.
    """
    sku = _unique_sku("MERGENULL")
    # seed_hot_row appends the sku to cleanup.skus itself.
    seed_hot_row(dis_admin, cleanup, sku_id=sku, mapping_version_id=consumer_mappings[CATALOGUE_SOURCE_ID])
    r0 = _read(dis_admin, sku)
    assert r0.attribute_staleness_map is None  # precondition: NULL stored map
    assert r0.last_source_event_at is None  # gate will pass via the IS NULL branch

    await _ingest_full(
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
        received_ts=BASE_TS,
    )
    r1 = _read(dis_admin, sku)
    # NOT wiped to NULL; exactly the carried tracked keys at received_ts.
    assert r1.attribute_staleness_map is not None
    assert set(r1.attribute_staleness_map) == {"current_retail_price", "unit_cost", "stock_qty"}
    assert set(r1.attribute_staleness_map.values()) == {BASE_TS.isoformat()}


async def test_merge_preserves_a_key_present_in_both_maps_incoming_wins(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    consumer_mappings: dict[str, int],
) -> None:
    """Concat-order guard (stored || EXCLUDED = incoming-wins): a key present in BOTH the
    stored and the incoming map with DIFFERENT timestamps must resolve to the INCOMING
    (newer) one. If the concat were reversed (EXCLUDED || stored, left-wins), the stale
    stored timestamp would shadow the fresh one and this assertion would fail — so this
    directly catches a right/left-wins reversal that the AC1 assertion also depends on.
    """
    sku = _unique_sku("MERGEORDER")
    cleanup.skus.append(sku)
    t1 = BASE_TS
    t2 = BASE_TS + timedelta(minutes=1)

    # W1 sets current_retail_price at t1 (stored map has the key).
    await _ingest_full(
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
    assert _read(dis_admin, sku).attribute_staleness_map["current_retail_price"] == t1.isoformat()
    # W2 carries current_retail_price again at t2 (incoming map has the SAME key, newer ts).
    await _ingest_minimal(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        price="9.99",
        qty="42",
        received_ts=t2,
    )
    # Incoming wins: t2, not the stale stored t1. (Reversed concat would leave t1 here.)
    assert _read(dis_admin, sku).attribute_staleness_map["current_retail_price"] == t2.isoformat()


async def test_older_snapshot_advances_nothing_in_the_map(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
) -> None:
    """The merge sits inside the event-time gate: an older-received snapshot skips the
    whole DO UPDATE, so no map key advances (and the row is untouched)."""
    sku = _unique_sku("MERGEOLD")
    cleanup.skus.append(sku)
    t1 = BASE_TS
    t0 = BASE_TS - timedelta(minutes=5)  # strictly older than the stored t1

    await _ingest_full(
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

    # An older snapshot with different values — the gate blocks the DO UPDATE entirely.
    # The rejected write is counted as a no-op, NOT a hot upsert. These counts
    # are EXACT and would go red if Fix 2 were reverted (pre-fix the catalogue path reported 1/0).
    await _ingest_full(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="OLD",
        category="Perishables",
        price="1.00",
        cost="9.99",
        qty="1",
        received_ts=t0,
        expected_hot=0,
        expected_noops=1,
    )
    r2 = _read(dis_admin, sku)
    assert r2.attribute_staleness_map == r1.attribute_staleness_map  # nothing advanced
    assert r2.last_updated_at == r1.last_updated_at  # no UPDATE fired


async def test_merge_is_load_bearing(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: prove the MERGE — not luck — preserves an omitted column's key.

    Swap ONLY the merge clause for the old WHOLESALE variant (``= EXCLUDED``), run the
    same write-1/write-2 sequence, and show ``unit_cost`` is DROPPED from the map — i.e.
    the AC2 keep-prior-timestamp assertion above would FAIL under the exact mistake the
    merge guards against. Mirrors ``test_conditional_stamp_is_load_bearing``.
    """
    import streaming_consumer.sinks.canonical as canonical

    monkeypatch.setattr(
        canonical,
        "_staleness_merge_clause",
        lambda: "attribute_staleness_map = EXCLUDED.attribute_staleness_map",
    )

    sku = _unique_sku("MERGENEG")
    cleanup.skus.append(sku)
    t1 = BASE_TS
    t2 = BASE_TS + timedelta(minutes=1)

    await _ingest_full(
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
    assert r1.attribute_staleness_map["unit_cost"] == t1.isoformat()  # present after write 1

    # Minimal write drops cost. Under WHOLESALE replace the whole map becomes the freshly
    # built {price, qty} map — unit_cost is WIPED (the bug the merge fixes).
    await _ingest_minimal(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        price="9.99",
        qty="42",
        received_ts=t2,
    )
    r2 = _read(dis_admin, sku)
    m2 = r2.attribute_staleness_map
    assert "unit_cost" not in m2  # DROPPED — the real merge would have held it at t1
    assert set(m2) == {"current_retail_price", "stock_qty"}


# -- The stamp trigger is NON-NULL-VALUE-PRESENT, not projected-membership -----------------------


async def test_blank_tracked_column_preserves_prior_key(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
) -> None:
    """AC2: a tracked column valued then BLANKED keeps its prior timestamp. The blank does not stamp
    (non-null trigger, Fix 1), so the built map omits it and the per-column merge preserves the prior
    key at its earlier value — not advanced, not wiped."""
    sku = _unique_sku("BLANKPRIOR")
    cleanup.skus.append(sku)
    t1 = BASE_TS
    t2 = BASE_TS + timedelta(minutes=1)

    # W1: unit_cost valued → stamped at t1.
    await _ingest_full(
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
    m1 = _read(dis_admin, sku).attribute_staleness_map
    assert m1["unit_cost"] == t1.isoformat()

    # W2: unit_cost BLANK (parse_decimal("") → NULL); price/qty still valued at the newer t2.
    await _ingest_full(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        category="Hardware",
        price="9.99",
        cost="",
        qty="42",
        received_ts=t2,
    )
    r2 = _read(dis_admin, sku)
    m2 = r2.attribute_staleness_map
    assert r2.unit_cost is None  # the value column was blanked
    assert m2["unit_cost"] == t1.isoformat()  # prior key PRESERVED (blank did not advance it)
    assert m2["current_retail_price"] == t2.isoformat()  # non-null tracked cols still advance
    assert m2["stock_qty"] == t2.isoformat()
    assert set(m2) == {"current_retail_price", "unit_cost", "stock_qty"}


async def test_blank_tracked_column_from_start_has_no_key(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
) -> None:
    """AC2 (never-valued → no key): a tracked column blank on the FIRST (INSERT-arm) write is not
    stamped, so it has no key in the persisted map at all."""
    sku = _unique_sku("BLANKINIT")
    cleanup.skus.append(sku)
    assert _row_count(dis_admin, sku) == 0  # confirms the INSERT arm

    await _ingest_full(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        category="Hardware",
        price="9.99",
        cost="",
        qty="42",
        received_ts=BASE_TS,
    )
    r = _read(dis_admin, sku)
    assert r.unit_cost is None
    m = r.attribute_staleness_map
    assert "unit_cost" not in m  # never carried a value → no key
    assert set(m) == {"current_retail_price", "stock_qty"}


async def test_resent_identical_nonnull_value_still_stamps(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
) -> None:
    """AC1/AC3: a re-sent IDENTICAL non-null value still stamps — staleness records confirmation,
    not change, so unit_cost advances t1 -> t2 even though its value did not move (distinct from the
    50b value-change stamps)."""
    sku = _unique_sku("RESENT")
    cleanup.skus.append(sku)
    t1 = BASE_TS
    t2 = BASE_TS + timedelta(minutes=1)

    await _ingest_full(
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
    assert _read(dis_admin, sku).attribute_staleness_map["unit_cost"] == t1.isoformat()

    # Identical cost re-sent at the newer t2.
    await _ingest_full(
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
    assert r2.unit_cost == Decimal("4.0000")  # value unchanged
    assert r2.attribute_staleness_map["unit_cost"] == t2.isoformat()  # yet the stamp advanced


async def test_blank_stamp_trigger_is_load_bearing(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Negative control: revert the trigger to PRESENCE-based (the pre-Fix-1 behavior) and prove a
    blanked column IS then stamped — i.e. the AC2 preserve assertion above would go red under the
    exact bug Fix 1 removes. Mirrors test_merge_is_load_bearing."""
    import streaming_consumer.sinks.canonical as canonical

    monkeypatch.setattr(
        canonical,
        "_staleness_stamp_keys",
        lambda projected, cols: sorted(set(projected) & cols),  # presence, not non-null value
    )

    sku = _unique_sku("BLANKNEG")
    cleanup.skus.append(sku)
    t1 = BASE_TS
    t2 = BASE_TS + timedelta(minutes=1)

    await _ingest_full(
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
    assert _read(dis_admin, sku).attribute_staleness_map["unit_cost"] == t1.isoformat()

    # Blank cost: under the presence-based trigger unit_cost is present (as None) → stamped → the map
    # advances it to t2 (the false-freshness bug). The real non-null trigger holds it at t1.
    await _ingest_full(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Widget",
        category="Hardware",
        price="9.99",
        cost="",
        qty="42",
        received_ts=t2,
    )
    m2 = _read(dis_admin, sku).attribute_staleness_map
    assert m2["unit_cost"] == t2.isoformat()  # ADVANCED despite blank — bug reproduced under revert


async def test_zero_value_tracked_column_still_stamps(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
) -> None:
    """Fix 1 guard (`is not None`, NOT truthiness): a genuinely ZERO tracked value stamps. Proven on
    a REAL persisted row — 0.00 price/cost and 0 qty are the exact case a truthiness filter would
    wrongly drop while passing on non-zero data. DB CHECKs are `>= 0`, so zeros are valid."""
    sku = _unique_sku("ZERO")
    cleanup.skus.append(sku)
    await _ingest_full(
        pipeline,
        dis_admin,
        storage,
        cleanup,
        stack_env,
        sku=sku,
        name="Zero",
        category="Hardware",
        price="0.00",
        cost="0.00",
        qty="0",
        received_ts=BASE_TS,
    )
    r = _read(dis_admin, sku)
    assert r.current_retail_price == Decimal("0.0000")
    assert r.unit_cost == Decimal("0.0000")
    assert r.stock_qty == Decimal("0.000")
    m = r.attribute_staleness_map
    assert set(m) == {"current_retail_price", "unit_cost", "stock_qty"}  # all three zeros stamped
    assert set(m.values()) == {BASE_TS.isoformat()}
