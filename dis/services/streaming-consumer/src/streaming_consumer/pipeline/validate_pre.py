"""Pre-mapping (source-shape) validation: semantic validation lives here.

The suite is the default derived from the mapping's rename keys
(``SourceShapeSuiteDef.from_rename`` — the rename map is the single statement of
what the engine will read; the live ``pre_validation_suite_ref`` is NULL = use
default). Structural drift fails here; the failure is audited and, when it
falls on the quarantine allowlist, held in quarantine — otherwise the message
nacks.
"""

from __future__ import annotations

import polars as pl

from dis_core.logging import LogContext
from dis_validation import SourceShapeResult, SourceShapeSuiteDef, run_source_shape
from streaming_consumer.pipeline.mapping import LoadedMapping


def run_pre_validation(
    loaded: LoadedMapping,
    frame: pl.DataFrame,
    *,
    tenant_id: str,
    trace_id: str,
) -> SourceShapeResult:
    """Judge the raw chunk in the tenant's vocabulary; typed failures, never raises."""
    suite = SourceShapeSuiteDef.from_rename(loaded.source.rename)
    return run_source_shape(
        suite,
        frame,
        log_context=LogContext(tenant_id=tenant_id, trace_id=trace_id),
    )
