"""Cross-channel dedup isolation (connector reuse): api and csv rows with the SAME
payload never collide. dis_channel is part of the dedup key, so find_prior scoped
to one channel must not return the other channel's row - proven on live 5433."""

from __future__ import annotations

from typing import TYPE_CHECKING
from uuid import UUID

import pytest

from csv_ingest_worker.bronze import BronzeRow, find_prior, insert_row
from dis_core.ids import new_uuid7
from dis_core.timestamps import now_utc
from dis_rls import rls_session
from dis_testing.fixtures import DEFAULT_SOURCE_ID, PRIMARY_STORE, PRIMARY_TENANT

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

_SHA = "c" * 64
_SPID = "run_xchan_0001"  # identical id on BOTH channels: dis_channel is the only discriminator


def _row(bronze_id: UUID, trace_id: UUID, channel: str) -> BronzeRow:
    return BronzeRow(
        id=bronze_id,
        tenant_id=PRIMARY_TENANT.uuid,
        store_id=PRIMARY_STORE.uuid,
        source_id=DEFAULT_SOURCE_ID,
        trace_id=trace_id,
        gcs_uri=(
            f"gs://b/tenant/{PRIMARY_TENANT.uuid}/source/{DEFAULT_SOURCE_ID}"
            f"/yyyy=2026/mm=07/dd=18/{trace_id}.csv"
        ),
        payload_size_bytes=10,
        payload_sha256=_SHA,
        row_count=1,
        source_payload_id=_SPID,
        template_id=new_uuid7(),
        original_filename=None,
        # INSIDE the dedup window, relative to now: find_prior filters
        # received_at >= now() - DEDUP_WINDOW_HOURS, so a fixed date would rot
        # into a permanent no-prior-found failure once it aged past the window.
        received_at=now_utc(),
        processing_status="RECEIVED",
        dis_channel=channel,
    )


async def test_api_and_csv_same_payload_do_not_dedup_cross_channel(
    engine: AsyncEngine, cleanup_traces: list[UUID]
) -> None:
    csv_trace, api_trace = new_uuid7(), new_uuid7()
    csv_id, api_id = new_uuid7(), new_uuid7()
    cleanup_traces.extend([csv_trace, api_trace])

    async with rls_session(engine, PRIMARY_TENANT.uuid) as conn:
        await insert_row(conn, _row(csv_id, csv_trace, "csv_upload"))
        await insert_row(conn, _row(api_id, api_trace, "api"))

    async with rls_session(engine, PRIMARY_TENANT.uuid) as conn:
        csv_prior = await find_prior(
            conn,
            upload_session_id=_SPID,
            payload_sha256=_SHA,
            tenant_id=str(PRIMARY_TENANT.uuid),
            trace_id=str(csv_trace),
        )  # default channel = csv_upload
        api_prior = await find_prior(
            conn,
            upload_session_id=_SPID,
            payload_sha256=_SHA,
            tenant_id=str(PRIMARY_TENANT.uuid),
            trace_id=str(api_trace),
            dis_channel="api",
        )

    assert csv_prior is not None and csv_prior.bronze_id == csv_id  # NOT the api row
    assert api_prior is not None and api_prior.bronze_id == api_id  # NOT the csv row
