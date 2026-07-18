"""Bronze sink unit surface: required-value key guards and the prior-row semantics.

The SQL itself is proven against the live schema by the integration tests; here the
pure logic is pinned: the dedup-key components are required values (rule 4), and
``PriorIngest.is_published`` is what splits full-no-op from resume-and-mark (D59).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest

from csv_ingest_worker.bronze import (
    CONTENT_TYPE,
    DIS_CHANNEL,
    BronzeRow,
    PriorIngest,
    find_prior,
    insert_row,
)
from dis_core.errors import EventContractError

_TENANT = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees
_TRACE = "019e8d88-4e76-7911-bb77-d8fcba1808a6"
_SHA = "a" * 64


class _ExplodingConnection:
    """A stand-in that fails the test if any SQL executes past the key guard."""

    async def execute(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no SQL may run when a dedup key component is missing")


@pytest.mark.parametrize(
    ("session_id", "sha", "bad_field"),
    [
        ("", _SHA, "upload_session_id"),
        ("   ", _SHA, "upload_session_id"),
        ("us_acme9k2l1mn4", "", "payload_sha256"),
        ("us_acme9k2l1mn4", "  ", "payload_sha256"),
    ],
)
async def test_missing_dedup_key_component_raises_before_any_sql(
    session_id: str, sha: str, bad_field: str
) -> None:
    # The idempotency key is a required value: missing -> dis-core error, never a
    # silent fallback, and the check must not silently "find nothing" instead.
    with pytest.raises(EventContractError) as exc_info:
        await find_prior(
            _ExplodingConnection(),  # type: ignore[arg-type]  # protocol stand-in
            upload_session_id=session_id,
            payload_sha256=sha,
            tenant_id=_TENANT,
            trace_id=_TRACE,
        )
    assert exc_info.value.field == bad_field
    assert exc_info.value.trace_id == _TRACE


def _prior(**overrides: Any) -> PriorIngest:
    base: dict[str, Any] = {
        "bronze_id": UUID("019e93f0-57ca-7470-9899-ba6532ff15e1"),
        "trace_id": UUID(_TRACE),
        "store_id": None,
        "source_id": "manual_csv_upload",
        "gcs_uri": "gs://b/k.csv",
        "received_at": datetime(2026, 6, 5, 10, 0, tzinfo=UTC),
        "published_at": None,
        "processing_status": "RECEIVED",
    }
    base.update(overrides)
    return PriorIngest(**base)


def test_prior_published_when_published_at_set() -> None:
    prior = _prior(published_at=datetime(2026, 6, 5, 10, 1, tzinfo=UTC), processing_status="PUBLISHED")
    assert prior.is_published


def test_prior_published_when_status_published_even_without_timestamp() -> None:
    # Defensive: status wins even if a backfill left published_at NULL.
    assert _prior(processing_status="PUBLISHED").is_published


def test_prior_unpublished_when_received_and_no_timestamp() -> None:
    # The resume-and-mark branch (D59): bronze landed, publish was lost.
    assert not _prior().is_published


def test_prior_failed_counts_as_unpublishable_no_op_input() -> None:
    # A FAILED prior is not published; the pipeline treats it as a no-op WITHOUT
    # re-publishing (preflight failure is terminal — pipeline test pins this).
    assert not _prior(processing_status="FAILED").is_published


def test_channel_and_content_type_constants() -> None:
    # The worker writes only the csv_upload channel (live CHECK vocab) as text/csv.
    assert DIS_CHANNEL == "csv_upload"
    assert CONTENT_TYPE == "text/csv"


# -- dis_channel parameterization regression (connector reuse) -------------------
#
# bronze.py gained an optional BronzeRow.dis_channel field (default DIS_CHANNEL) and a
# find_prior dis_channel kwarg (default DIS_CHANNEL) so the connector SDK can reuse the
# same bronze sink with dis_channel="api". These tests prove the csv-ingest-worker path
# (which passes NEITHER) is byte-for-byte unchanged, and that the api override flows.


class _CapturingConnection:
    """Captures the bind params of the single execute; returns no rows."""

    def __init__(self) -> None:
        self.params: dict[str, Any] | None = None

    async def execute(self, _statement: Any, params: dict[str, Any] | None = None) -> Any:
        self.params = params

        class _Result:
            @staticmethod
            def one_or_none() -> None:
                return None

        return _Result()


def _bronze_row(**overrides: Any) -> BronzeRow:
    base: dict[str, Any] = {
        "id": UUID("019e93f0-57ca-7470-9899-ba6532ff15e1"),
        "tenant_id": UUID(_TENANT),
        "store_id": UUID("019e5e3c-b5d3-705f-9002-2451c4ca2700"),
        "source_id": "manual_csv_upload",
        "trace_id": UUID(_TRACE),
        "gcs_uri": "gs://b/tenant/x/source/s/yyyy=2026/mm=06/dd=05/t.csv",
        "payload_size_bytes": 10,
        "payload_sha256": _SHA,
        "row_count": 3,
        "source_payload_id": "us_acme9k2l1mn4",
        "template_id": UUID("019e93f0-57ca-7470-9899-ba6532ff1600"),
        "original_filename": "orders.csv",
        "received_at": datetime(2026, 6, 5, 10, 0, tzinfo=UTC),
        "processing_status": "RECEIVED",
    }
    base.update(overrides)
    return BronzeRow(**base)


def test_bronze_row_defaults_dis_channel_to_csv_upload() -> None:
    # csv-ingest-worker constructs BronzeRow without dis_channel: it must default to
    # csv_upload so the CSV worker's emitted row is unchanged by the connector work.
    assert _bronze_row().dis_channel == DIS_CHANNEL == "csv_upload"


async def test_insert_row_defaults_to_csv_upload_and_text_csv() -> None:
    # The default (CSV worker) path stamps csv_upload + text/csv exactly as before.
    conn = _CapturingConnection()
    await insert_row(conn, _bronze_row())  # type: ignore[arg-type]  # protocol stand-in
    assert conn.params is not None
    assert conn.params["dis_channel"] == "csv_upload"
    assert conn.params["content_type"] == "text/csv"


async def test_insert_row_honours_api_channel_override() -> None:
    # The connector passes dis_channel="api"; content_type stays text/csv (both land CSV).
    conn = _CapturingConnection()
    await insert_row(conn, _bronze_row(dis_channel="api"))  # type: ignore[arg-type]
    assert conn.params is not None
    assert conn.params["dis_channel"] == "api"
    assert conn.params["content_type"] == "text/csv"


async def test_find_prior_defaults_channel_to_csv_upload() -> None:
    # The CSV worker calls find_prior without dis_channel: the dedup query must still
    # filter on csv_upload, byte-for-byte the pre-connector behaviour.
    conn = _CapturingConnection()
    await find_prior(
        conn,  # type: ignore[arg-type]  # protocol stand-in
        upload_session_id="us_acme9k2l1mn4",
        payload_sha256=_SHA,
        tenant_id=_TENANT,
        trace_id=_TRACE,
    )
    assert conn.params is not None
    assert conn.params["channel"] == "csv_upload"


async def test_find_prior_honours_api_channel() -> None:
    # The connector scopes its dedup lookup to the api channel.
    conn = _CapturingConnection()
    await find_prior(
        conn,  # type: ignore[arg-type]  # protocol stand-in
        upload_session_id="run_square_0001",
        payload_sha256=_SHA,
        tenant_id=_TENANT,
        trace_id=_TRACE,
        dis_channel="api",
    )
    assert conn.params is not None
    assert conn.params["channel"] == "api"
