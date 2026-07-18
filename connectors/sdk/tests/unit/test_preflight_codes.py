"""The connector preflight verdicts and the closed reason vocabulary.

Structural only: the verdict turns on the header and the row count, never cell values.
Every reason maps to a dis-audit ``FailureCode`` (the emit-site rule), canary-pinned.
"""

from __future__ import annotations

from dis_audit import FailureCode
from thalamus_connector_sdk.adapter import Domain, ExtractResult, ExtractRow
from thalamus_connector_sdk.preflight import run_preflight
from thalamus_connector_sdk.reason_codes import (
    REASON_TO_FAILURE_CODE,
    ConnectorReasonCode,
    failure_code_for_reason,
)

_HEADER = ("sku_id", "product_name", "current_retail_price")
_DOMAIN = Domain.CATALOG


def _extract(header: tuple[str, ...], rows: tuple[ExtractRow, ...]) -> ExtractResult:
    return ExtractResult(domain=_DOMAIN, header=header, rows=rows, next_cursor=None)


def test_preflight_ok_with_rows() -> None:
    result = run_preflight(_extract(_HEADER, (ExtractRow({"sku_id": "A-1"}),)))
    assert result.ok
    assert result.row_count == 1
    assert result.columns == _HEADER
    assert result.reason is None


def test_preflight_empty_rows_is_extract_empty() -> None:
    result = run_preflight(_extract(_HEADER, ()))
    assert not result.ok
    assert result.reason is ConnectorReasonCode.EXTRACT_EMPTY


def test_preflight_no_header_is_schema_unrecognized() -> None:
    result = run_preflight(_extract((), (ExtractRow({"x": "y"}),)))
    assert not result.ok
    assert result.reason is ConnectorReasonCode.SCHEMA_UNRECOGNIZED


def test_every_reason_maps_to_a_failure_code() -> None:
    # Closed vocabulary: every reason has exactly one FailureCode (no KeyError path).
    for reason in ConnectorReasonCode:
        assert reason in REASON_TO_FAILURE_CODE
        assert isinstance(failure_code_for_reason(reason), FailureCode)


def test_structural_reasons_map_to_preflight_members() -> None:
    assert failure_code_for_reason(ConnectorReasonCode.EXTRACT_EMPTY) is FailureCode.PREFLIGHT_NO_DATA_ROWS
    assert (
        failure_code_for_reason(ConnectorReasonCode.SCHEMA_UNRECOGNIZED) is FailureCode.PREFLIGHT_NO_COLUMNS
    )
    assert failure_code_for_reason(ConnectorReasonCode.AUTH_FAILED) is FailureCode.INFRA_FAILURE
