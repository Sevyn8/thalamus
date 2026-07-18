"""Structural preflight over an extracted batch, mirroring the CSV worker's contract.

Structural ONLY: it inspects the header and the row count, never cell values, and never
propagates vendor error text. A failure yields a stable :class:`ConnectorReasonCode`,
which the pipeline turns into a FAILED bronze row plus a FAILURE audit and NO publish
(the write-then-conditionally-publish rule, D5).
"""

from __future__ import annotations

from thalamus_connector_sdk.adapter import ExtractResult, PreflightResult
from thalamus_connector_sdk.reason_codes import ConnectorReasonCode


def run_preflight(extract: ExtractResult) -> PreflightResult:
    """Structural verdict for one extracted batch.

    - No header columns -> SCHEMA_UNRECOGNIZED (the batch is not mappable).
    - Zero rows -> EXTRACT_EMPTY (nothing to land).
    - Otherwise ok, carrying the row count and the header columns.
    """
    columns = extract.header
    row_count = len(extract.rows)
    if not columns:
        return PreflightResult(
            ok=False,
            row_count=row_count,
            columns=columns,
            reason=ConnectorReasonCode.SCHEMA_UNRECOGNIZED,
            detail="extract produced no header columns",
        )
    if row_count == 0:
        return PreflightResult(
            ok=False,
            row_count=0,
            columns=columns,
            reason=ConnectorReasonCode.EXTRACT_EMPTY,
            detail="extract produced zero rows",
        )
    return PreflightResult(ok=True, row_count=row_count, columns=columns)
