"""Slice 52b write side: per-failure detail → failure_context.failures[], value-free audit.

AC1 (persist what the failure carried, OMIT what it did not) is pinned at the element
builder across ALL THREE failure shapes:
  - a value-level Pandera failure (value + column + row_index, no mapping fields),
  - a structural / frame-level failure (only check + reason — the element must be EXACTLY
    {check, reason}, proving absent fields are omitted, never null-filled),
  - a mapping cell-normalization failure (adds source_column / expected_format /
    transform_index).
AC2 (the audit/quarantine shared-failures seam) drives the SAME failures list through the
audit projection (``_emit_gate_failure``) and asserts the offending value reaches NO audit
event, while the quarantine element keeps it.
"""

from __future__ import annotations

import types
from typing import Any, cast

from dis_audit import Stage
from dis_core.ids import new_uuid7
from streaming_consumer.orchestrate import ConsumerPipeline
from streaming_consumer.sinks.audit import ConsumerAudit
from streaming_consumer.sinks.quarantine import GateFailure, _failure_element

# A distinctive offending value (PAN-shaped) that must NEVER reach an audit event.
_SECRET_VALUE = "4111111111111111"


# -- AC1: the element builder persists present fields, omits absent ones ------------


def test_value_level_failure_element_omits_mapping_only_fields() -> None:
    # A value-level Pandera failure (source/canonical shape): value + column + row_index,
    # but NONE of the mapping-only fields.
    gf = GateFailure(check="numeric", reason="not a number", column="price", row_index=3, value="abc")
    chunk_el = _failure_element(gf, include_row_index=True)
    assert chunk_el == {
        "check": "numeric",
        "reason": "not a number",
        "column": "price",
        "row_index": 3,
        "value": "abc",
    }
    # The row builder hoists row_index to the row_offset column, so it is omitted here.
    row_el = _failure_element(gf, include_row_index=False)
    assert row_el == {"check": "numeric", "reason": "not a number", "column": "price", "value": "abc"}
    for key in ("source_column", "expected_format", "transform_index"):
        assert key not in chunk_el and key not in row_el


def test_structural_failure_element_is_exactly_check_and_reason() -> None:
    # A frame-level (structural) failure: column / row_index / value ALL absent. The
    # element must be EXACTLY {check, reason} — absent fields OMITTED, not null-filled.
    gf = GateFailure(check="column_in_dataframe", reason="missing column 'sku'")
    exact = {"check": "column_in_dataframe", "reason": "missing column 'sku'"}
    assert _failure_element(gf, include_row_index=True) == exact
    assert _failure_element(gf, include_row_index=False) == exact


def test_mapping_cell_failure_element_carries_all_mapping_fields() -> None:
    # The mapping cell-normalization failure — the only type with source_column /
    # expected_format / transform_index.
    gf = GateFailure(
        check="cast:qty",
        reason="cast failed",
        column="qty",
        row_index=2,
        value="abc",
        source_column="quantity",
        expected_format="int",
        transform_index=0,
    )
    assert _failure_element(gf, include_row_index=True) == {
        "check": "cast:qty",
        "reason": "cast failed",
        "column": "qty",
        "row_index": 2,
        "value": "abc",
        "source_column": "quantity",
        "expected_format": "int",
        "transform_index": 0,
    }


def test_value_capped_wider_than_the_descriptions() -> None:
    # The deliberate asymmetry (52b): value is data future correction needs whole, so it
    # is capped at 2048 — wider than check (256) and reason (512), which are descriptions.
    gf = GateFailure(check="c" * 300, reason="r" * 600, value="v" * 3000)
    el = _failure_element(gf, include_row_index=True)
    assert len(cast(str, el["check"])) == 256
    assert len(cast(str, el["reason"])) == 512
    assert len(cast(str, el["value"])) == 2048


def test_falsy_but_present_optional_ints_survive() -> None:
    # transform_index=0 (the first op) and row_index=0 (the first row) are real values,
    # not "absent": the builder keys on `is not None`, NOT truthiness, so 0 must survive.
    gf = GateFailure(check="cast", reason="bad", row_index=0, transform_index=0)
    el = _failure_element(gf, include_row_index=True)
    assert el["transform_index"] == 0
    assert el["row_index"] == 0  # falsy but present — not dropped by a truthiness test


# -- AC2: the audit/quarantine shared-failures seam (audit stays value-free) --------


class _RecordingAudit:
    """Captures every emit() kwargs bag for inspection."""

    def __init__(self) -> None:
        self.emitted: list[dict[str, Any]] = []

    async def emit(self, **kwargs: Any) -> None:
        self.emitted.append(kwargs)


async def test_audit_projection_never_carries_the_offending_value() -> None:
    # ONE failures list feeds both the quarantine hold (keeps value) AND the audit
    # projection (must drop it). Drive _emit_gate_failure with a value-bearing failure and
    # assert the value appears NOWHERE across the emitted audit events.
    failures = [
        GateFailure(check="numeric", reason="not a number", column="pan", row_index=0, value=_SECRET_VALUE),
    ]
    audit = _RecordingAudit()
    # Only self.audit is touched by _emit_gate_failure — construct the instance without
    # running __init__ and stub the one attribute it reads.
    pipeline = ConsumerPipeline.__new__(ConsumerPipeline)
    pipeline.audit = cast(ConsumerAudit, audit)

    event = types.SimpleNamespace(tenant_id=new_uuid7(), trace_id=new_uuid7())
    fetched = types.SimpleNamespace(
        bronze=types.SimpleNamespace(bronze_id=new_uuid7()),
        frame=types.SimpleNamespace(height=1),
    )
    loaded = types.SimpleNamespace(mapping_version_id=1)
    ctx = types.SimpleNamespace(lap=lambda: 1)

    await pipeline._emit_gate_failure(
        Stage.PRE_MAPPING_VALIDATED,
        cast(Any, event),
        cast(Any, fetched),
        cast(Any, loaded),
        cast(Any, ctx),
        failures=failures,
    )

    assert audit.emitted, "the audit projection emitted nothing"
    assert _SECRET_VALUE not in repr(audit.emitted), "offending value leaked into audit (seam broken)"
    # The SAME failure, through the quarantine element, DOES keep the value.
    assert _failure_element(failures[0], include_row_index=True)["value"] == _SECRET_VALUE
