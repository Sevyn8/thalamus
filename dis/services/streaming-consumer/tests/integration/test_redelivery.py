"""AC8: at-least-once redelivery does not corrupt canonical.

Execute-time item 1 honoured: the chunk's rows carry DISTINCT source event
timestamps, so the hot-table assertion proves EVENT-TIME-WINS (the later-ts
row's price holds through every replay and through a late-arriving older
event), not merely the ``>=`` exact-tie-overwrite path.

REVISED BY MIGRATION 0019. This docstring used to read: "the same event processed
twice appends event rows BOTH times (review-confirmed by this test's count
assertions); correctness is the D33 read-time window + the D64 conditional upsert."
That was asserted here as CORRECT — ``event_rows == 4`` for two deliveries — and it is
why the duplication survived review until a real upload reached 328 x 5 = 1640 rows
unattended.

Two things were wrong with it. The read-time window it relied on was never built for
any consumer (the query below is hand-written in this test and nowhere else), so
re-appended rows were simply counted twice by every reader. And a REDELIVERY is not a
CORRECTION: D33's append-only posture exists for the second, not the first.

Now: a redelivery is SUPPRESSED (identical payload hash under an existing dedup key),
while a correction still appends. Transactional idempotency is still not the mechanism
 — ``uq_*_redelivery`` plus the in-transaction filter is. The event-time-wins
assertions below are unchanged and still prove D64.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TYPE_CHECKING

import pytest
from sqlalchemy import text

from dis_core.ids import new_uuid7
from dis_testing.fixtures import PRIMARY_TENANT
from streaming_consumer.orchestrate import ConsumerPipeline

from .conftest import SALE_SOURCE_ID, Cleanup, sale_csv, seed_chunk, seed_hot_row, ts

if TYPE_CHECKING:
    from sqlalchemy.engine import Engine

    from dis_storage.client import StorageClient

pytestmark = pytest.mark.integration


async def test_redelivery_appends_and_read_time_truth_holds(
    pipeline: ConsumerPipeline,
    dis_admin: Engine,
    storage: StorageClient,
    cleanup: Cleanup,
    stack_env: dict[str, str],
    consumer_mappings: dict[str, int],
) -> None:
    sku = f"RD-{new_uuid7().hex[:10]}"
    txn = f"T-{new_uuid7().hex[:8]}"
    seed_hot_row(dis_admin, cleanup, sku_id=sku, mapping_version_id=consumer_mappings[SALE_SOURCE_ID])

    # DISTINCT source event timestamps: the later row (ts+30) carries the price
    # that must win and HOLD (execute-time item 1).
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

    # First delivery, then an at-least-once REDELIVERY of the same event.
    assert (await pipeline.process(chunk.event)).disposition == "written"
    second = await pipeline.process(chunk.event)
    assert second.disposition == "written"
    # The redelivery saw every row as a prior-key hit (the D42 duplicate path) — and as
    # of 0019 it also SUPPRESSED all of them rather than re-appending.
    assert second.report is not None and len(second.report.duplicates) == 2
    assert second.report.event_rows_written == 0
    assert second.report.event_rows_suppressed == 2

    def _hot_price() -> Decimal:
        with dis_admin.begin() as conn:
            return Decimal(
                str(
                    conn.execute(
                        text(
                            "SELECT current_retail_price FROM canonical.store_sku_current_position "
                            "WHERE tenant_id = CAST(:tenant AS uuid) AND sku_id = :sku"
                        ),
                        {"tenant": str(PRIMARY_TENANT.uuid), "sku": sku},
                    ).scalar_one()
                )
            )

    with dis_admin.begin() as conn:
        event_rows = conn.execute(
            text("SELECT COUNT(*) FROM canonical.store_sku_sale_events WHERE trace_id = CAST(:t AS uuid)"),
            {"t": str(chunk.trace_id)},
        ).scalar_one()
        survivors = conn.execute(
            text(
                "SELECT COUNT(*) FROM ("
                "  SELECT ROW_NUMBER() OVER ("
                "           PARTITION BY tenant_id, store_id, source_id, source_event_id"
                "           ORDER BY source_sale_timestamp DESC, last_updated_at DESC, id DESC) AS rn"
                "  FROM canonical.store_sku_sale_events WHERE trace_id = CAST(:t AS uuid)"
                ") latest WHERE rn = 1"
            ),
            {"t": str(chunk.trace_id)},
        ).scalar_one()
        hot_count = conn.execute(
            text(
                "SELECT COUNT(*) FROM canonical.store_sku_current_position "
                "WHERE tenant_id = CAST(:tenant AS uuid) AND sku_id = :sku"
            ),
            {"tenant": str(PRIMARY_TENANT.uuid), "sku": sku},
        ).scalar_one()

    # 0019: the redelivery is SUPPRESSED, so 2 rows total rather than the 4 this
    # previously asserted. The read-time window answers 2 either way — which is exactly
    # why the old count went unnoticed: the window's answer was correct while the raw
    # table quietly doubled, and nothing in production ran the window.
    assert event_rows == 2
    assert survivors == 2
    # No double-count on the hot side: one row, the LATER-ts price (event-time-wins).
    assert hot_count == 1
    assert _hot_price() == Decimal("12.4900")

    # A late-arriving OLDER event (new bronze/trace, earlier ts, same SKU) lands
    # in the event table but does NOT overwrite newer hot state (architecture
    # 2.3.1 — the D64 condition rejects it).
    late_old = seed_chunk(
        dis_admin,
        storage,
        cleanup,
        csv_data=sale_csv([(ts(-120), sku, "1", "5.00", "4.50", f"T-{new_uuid7().hex[:8]}", "1")]),
        source_id=SALE_SOURCE_ID,
        bronze_bucket=stack_env["GCS_BUCKET_BRONZE"],
    )
    assert (await pipeline.process(late_old.event)).disposition == "written"
    assert _hot_price() == Decimal("12.4900")  # unchanged: older event lost
