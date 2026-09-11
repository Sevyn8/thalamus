"""Migration 0019: a REDELIVERY is idempotent; a CORRECTION still lands.

THE INCIDENT THESE PIN, observed 2026-07-31 on the first sales data the platform ever
held: a 328-row upload failed a CHECK and nacked; once the template was corrected each
Pub/Sub retry SUCCEEDED and each success appended a COMPLETE duplicate set. The table
reached 1640 rows (328 x 5) with nobody touching it. The retry mechanism was the
duplicator — not an operator, and not a weakness in the retry policy, which is correct
and unchanged.

Three distinct proofs, because they fail in different ways:

- ``test_same_chunk_twice_does_not_duplicate`` — the SINK's filter, driven through the
  pipeline. Two deliveries, one row set.
- ``test_correction_still_appends`` — the guard against over-reach. D33 is not repealed:
  a different payload under the same dedup key is a correction and must append.
- ``test_pubsub_redelivery_n_times_is_stable`` — THE ACTUAL SCENARIO, through
  ``process_message`` (the real Pub/Sub entry point that retried), N times. Not the same
  test as "same chunk twice": it exercises envelope decode, disposition and ack on every
  cycle, which is the path that actually ran.
- ``test_unique_index_refuses_a_raw_duplicate`` — the DB BACKSTOP, independent of the
  sink. If the filter is ever refactored away, this still fails.

The pre-0019 behaviour was asserted as correct by ``test_redelivery.py`` (``event_rows
== 4``, "2 rows per delivery"), which is why the duplication survived review. That test
now asserts the fixed count; these add the cases it never had.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from dis_canonical import StoreSkuSaleEvent
from dis_core.ids import new_uuid7
from dis_testing.fixtures import PRIMARY_TENANT
from streaming_consumer.clients.pubsub import process_message
from streaming_consumer.orchestrate import ConsumerPipeline

from .conftest import SALE_SOURCE_ID, Cleanup, sale_csv, seed_chunk, seed_hot_row, ts

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from dis_storage.client import StorageClient

pytestmark = pytest.mark.integration

_REDELIVERIES = 5  # the observed multiplier: 328 x 5 = 1640


def _event_count(dis_admin: Engine, trace_id: object) -> int:
    with dis_admin.begin() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COUNT(*) FROM canonical.store_sku_sale_events WHERE trace_id = CAST(:t AS uuid)"
                ),
                {"t": str(trace_id)},
            ).scalar_one()
        )


def _distinct_row_hashes(dis_admin: Engine, trace_id: object) -> int:
    with dis_admin.begin() as conn:
        return int(
            conn.execute(
                text(
                    "SELECT COUNT(DISTINCT row_hash) FROM canonical.store_sku_sale_events "
                    "WHERE trace_id = CAST(:t AS uuid)"
                ),
                {"t": str(trace_id)},
            ).scalar_one()
        )


async def test_same_chunk_twice_does_not_duplicate(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    consumer_mappings: dict[str, int],
) -> None:
    """Two deliveries of one chunk leave ONE row set. Pre-0019 this was 4 rows."""
    sku = f"RI-{new_uuid7().hex[:10]}"
    txn = f"T-{new_uuid7().hex[:8]}"
    seed_hot_row(dis_admin, cleanup, sku_id=sku, mapping_version_id=consumer_mappings[SALE_SOURCE_ID])
    chunk = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=sale_csv(
            [
                (ts(0), sku, "2", "9.99", "8.50", txn, "1"),
                (ts(30), sku, "1", "12.49", "11.99", txn, "2"),
            ]
        ),
        source_id=SALE_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
    )

    first = await pipeline.process(chunk.event)
    assert first.disposition == "written"
    assert first.report is not None
    assert first.report.event_rows_written == 2
    assert first.report.event_rows_suppressed == 0
    assert _event_count(dis_admin, chunk.trace_id) == 2

    second = await pipeline.process(chunk.event)
    assert second.disposition == "written"
    assert second.report is not None
    # The rows were RECOGNISED (both dedup keys hit) and SUPPRESSED, not written.
    assert len(second.report.duplicates) == 2
    assert second.report.event_rows_written == 0
    assert second.report.event_rows_suppressed == 2
    # THE ASSERTION THE INCIDENT NEEDED: unchanged, not doubled.
    assert _event_count(dis_admin, chunk.trace_id) == 2


async def test_correction_still_appends(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    consumer_mappings: dict[str, int],
) -> None:
    """A corrected line under the SAME dedup key appends a second row.

    The guard against the fix over-reaching. Same ``transaction_id:line_item_seq``, so
    the same ``source_event_id``; a different price, so a different ``row_hash``. If
    uniqueness had been put on the dedup key ALONE, this row would have been silently
    dropped and the correction lost — which is exactly why ``row_hash`` is in the index.
    """
    sku = f"RC-{new_uuid7().hex[:10]}"
    txn = f"T-{new_uuid7().hex[:8]}"
    seed_hot_row(dis_admin, cleanup, sku_id=sku, mapping_version_id=consumer_mappings[SALE_SOURCE_ID])

    original = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=sale_csv([(ts(0), sku, "2", "9.99", "8.50", txn, "1")]),
        source_id=SALE_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
    )
    assert (await pipeline.process(original.event)).disposition == "written"

    # The source re-sends the SAME line with a corrected price, as a new bronze object.
    corrected = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=sale_csv([(ts(30), sku, "2", "9.99", "7.25", txn, "1")]),
        source_id=SALE_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
    )
    result = await pipeline.process(corrected.event)
    assert result.disposition == "written"
    assert result.report is not None
    assert result.report.event_rows_written == 1, "a correction must LAND, not be suppressed"
    assert result.report.event_rows_suppressed == 0

    with dis_admin.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT unit_sale_price, row_hash FROM canonical.store_sku_sale_events "
                "WHERE tenant_id = CAST(:tenant AS uuid) AND sku_id = :sku "
                "ORDER BY source_sale_timestamp"
            ),
            {"tenant": str(PRIMARY_TENANT.uuid), "sku": sku},
        ).all()
    assert len(rows) == 2, "both the original and the correction are retained (D33)"
    assert rows[0].row_hash != rows[1].row_hash, "different payloads must hash differently"

    # And the read-time window still collapses the key to the correction. NOTE: this
    # query is written HERE, by hand — no platform-owned view or resolver implements it.
    with dis_admin.begin() as conn:
        survivor = conn.execute(
            text(
                "SELECT unit_sale_price FROM ("
                "  SELECT unit_sale_price, ROW_NUMBER() OVER ("
                "           PARTITION BY tenant_id, store_id, source_id, source_event_id"
                "           ORDER BY source_sale_timestamp DESC, last_updated_at DESC, id DESC"
                "         ) AS rn"
                "  FROM canonical.store_sku_sale_events"
                "  WHERE tenant_id = CAST(:tenant AS uuid) AND sku_id = :sku"
                ") latest WHERE rn = 1"
            ),
            {"tenant": str(PRIMARY_TENANT.uuid), "sku": sku},
        ).scalar_one()
    assert str(survivor).startswith("7.25"), "latest-wins returns the correction"


async def test_pubsub_redelivery_n_times_is_stable(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    consumer_mappings: dict[str, int],
) -> None:
    """THE ACTUAL SCENARIO: the same ``ingress.ready`` message redelivered N times.

    Distinct from ``test_same_chunk_twice`` because it goes through
    ``process_message`` — envelope decode, disposition, ack — which is the path Pub/Sub
    actually drove when the retry policy replayed the nacked message. Pre-0019 this
    produced ``rows x N``; the incident was N=5 against 328 rows.
    """
    sku = f"RN-{new_uuid7().hex[:10]}"
    txn = f"T-{new_uuid7().hex[:8]}"
    seed_hot_row(dis_admin, cleanup, sku_id=sku, mapping_version_id=consumer_mappings[SALE_SOURCE_ID])
    chunk = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=sale_csv(
            [
                (ts(0), sku, "1", "9.99", "8.50", txn, "1"),
                (ts(15), sku, "2", "9.99", "8.50", txn, "2"),
                (ts(30), sku, "1", "12.49", "11.99", txn, "3"),
            ]
        ),
        source_id=SALE_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
    )
    payload = chunk.event.model_dump_json(exclude_none=True).encode()

    for attempt in range(1, _REDELIVERIES + 1):
        decision = await process_message(pipeline, payload)
        assert decision == "ack", f"delivery {attempt} must ack"
        count = _event_count(dis_admin, chunk.trace_id)
        assert count == 3, (
            f"after delivery {attempt} of {_REDELIVERIES} the table holds {count} rows, "
            f"expected 3. Pre-0019 this grew by 3 per delivery (the 328 x N incident)."
        )

    # Every landed row is a distinct logical line, not a repeat.
    assert _distinct_row_hashes(dis_admin, chunk.trace_id) == 3


async def test_unique_index_refuses_a_raw_duplicate(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    consumer_mappings: dict[str, int],
) -> None:
    """The DB backstop, proven WITHOUT the sink.

    ``uq_ssse_redelivery`` must reject a byte-identical row even if the in-transaction
    filter is bypassed entirely — the case the filter CANNOT cover, because it is
    read-then-write and two instances can interleave. This is also the regression guard
    for someone later removing the filter and assuming the index has their back.

    THE COLUMN LIST IS DERIVED FROM THE MODEL, NOT WRITTEN OUT, and not because it is
    shorter. The first version of this used a positional
    ``INSERT INTO … SELECT col, col, …`` and failed with a DatatypeMismatch, because
    ``ALTER TABLE ADD COLUMN`` APPENDS: on a database migrated 0018 -> 0019 ``row_hash``
    is physically the LAST column (34), while the DDL file declares it after
    ``source_event_id`` — so physical order differs between a migrated and a
    freshly-bootstrapped database, and any positional SQL over these tables is wrong on
    one of them. (Harmless elsewhere: ``resident_fingerprint`` sorts by column NAME, and
    ``_event_insert_sql`` names its columns. This test was the only positional SQL.)
    Deriving from ``model_fields`` — the same source ``_event_insert_sql`` uses — makes
    the statement order-independent and unable to drift from the schema.
    """
    sku = f"RU-{new_uuid7().hex[:10]}"
    txn = f"T-{new_uuid7().hex[:8]}"
    seed_hot_row(dis_admin, cleanup, sku_id=sku, mapping_version_id=consumer_mappings[SALE_SOURCE_ID])
    chunk = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=sale_csv([(ts(0), sku, "1", "9.99", "8.50", txn, "1")]),
        source_id=SALE_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
    )
    assert (await pipeline.process(chunk.event)).disposition == "written"

    # Clone the landed row with a fresh PK and a fresh last_updated_at, changing NOTHING
    # in the unique key. Columns NAMED on both sides, so physical order cannot matter.
    carried = [
        name
        for name in StoreSkuSaleEvent.model_fields
        if name not in ("id", "last_updated_at")  # id: fresh PK; last_updated_at: NOW()
    ]
    assert "row_hash" in carried, "the clone must carry row_hash or the index cannot arbitrate"
    column_list = ", ".join(carried)
    clone = (
        f"INSERT INTO canonical.store_sku_sale_events (id, last_updated_at, {column_list}) "  # noqa: S608 - model-derived identifiers
        f"SELECT uuidv7(), NOW(), {column_list} "
        "FROM canonical.store_sku_sale_events WHERE trace_id = CAST(:t AS uuid)"
    )
    with pytest.raises(IntegrityError, match="uq_ssse_redelivery"):
        with dis_admin.begin() as conn:
            conn.execute(text(clone), {"t": str(chunk.trace_id)})

    assert _event_count(dis_admin, chunk.trace_id) == 1, "the refused insert left nothing behind"
