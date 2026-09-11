"""Unit tests for the quarantine console endpoints.

Two halves. PURE: the single crosswalk (display forward == filter reverse, no drift),
the Context composition, the type-tagged id parse, the ISO rendering. WIRE: the parts
of both endpoints that resolve BEFORE any database call - auth/scope (401/403), query
filter validation (422), and a malformed/unknown tagged id (404) - exercised through
the real app over an unreachable DB, so the dependency chain and the envelope handlers
are the real ones. The DB-backed behaviour (isolation, filters, counts, detail) is the
integration suite's job.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from dis_core.errors import TenantScopeError
from dis_core.ids import new_uuid7
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.handlers.quarantine import (
    _compose_context,
    _iso,
    _parse_item_id,
    _to_failures,
    _to_list_row,
)
from dis_ui_server.models import QuarantinedChunk, QuarantinedRow
from dis_ui_server.repos.quarantine import _list_filters, _tenant_term
from dis_ui_server.schemas.quarantine import (
    QuarantineDetail,
    QuarantineListRow,
    StageWire,
    stage_db_values_for,
    stage_to_wire,
    status_db_values_for,
    status_to_wire,
)

# Re-declared locally (the unit suite's convention: no tests package, importlib mode).
TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees

# The live CHECK vocabularies (introspected 15a Task 0): the row 6-member subset plus
# the three chunk-only pre-lookup stages. Every member MUST forward-map (no silent gap).
_ALL_DB_STAGES = (
    "PRE_MAPPING_VALIDATION",
    "MAPPING_EXECUTION",
    "POST_MAPPING_VALIDATION",
    "IDENTITY_VALIDATION",
    "CANONICAL_WRITE",
    "OTHER",
    "PRE_INGEST_PII",
    "BRONZE_WRITE",
    "MAPPING_LOOKUP",
)
_ALL_WIRE_STAGES: tuple[StageWire, ...] = ("source-shape", "canonical-shape", "fk", "normalization", "other")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# -- tenant predicate is UNCONDITIONAL (pinned independent of RLS) ------------------


@pytest.mark.parametrize("model", [QuarantinedRow, QuarantinedChunk])
def test_list_filters_tenant_predicate_is_conditional_on_platform(
    model: type[QuarantinedRow] | type[QuarantinedChunk],
) -> None:
    # Structural catastrophe guard: the tenant predicate is
    # PRESENT for a pinned (TENANT) scope and OMITTED for PLATFORM see-all -- conditioned
    # on is_platform, NEVER on tenant_id being absent. quarantine.* is RLS ON, so this
    # pins the predicate so it cannot quietly vanish for TENANT (leaving isolation on RLS
    # alone) nor wrongly persist for PLATFORM (defeating see-all).
    tenant_id = new_uuid7()
    pinned = _list_filters(
        model,
        ReadScope(is_platform=False, tenant_id=tenant_id),
        source=None,
        stages=None,
        statuses=None,
        cutoff=None,
    )
    assert any("tenant_id" in str(term) for term in pinned), "pinned (TENANT) scope lost its tenant predicate"
    platform = _list_filters(
        model,
        ReadScope(is_platform=True, tenant_id=None),
        source=None,
        stages=None,
        statuses=None,
        cutoff=None,
    )
    assert not any("tenant_id" in str(term) for term in platform), (
        "PLATFORM see-all scope still carries a tenant predicate -> see-all defeated"
    )


@pytest.mark.parametrize("model", [QuarantinedRow, QuarantinedChunk])
def test_tenant_term_refuses_a_pinned_scope_without_a_tenant(
    model: type[QuarantinedRow] | type[QuarantinedChunk],
) -> None:
    # Locks the discriminator as ``scope.is_platform``, NOT tenant-absence: a PINNED
    # (non-platform) scope that somehow lacks a tenant is REFUSED, never silently left
    # unscoped. Catches a mutation that keys the predicate on ``scope.tenant_id is None``
    # (which would drop the predicate for a tenant-less pinned scope instead of raising).
    with pytest.raises(TenantScopeError):
        _tenant_term(model, ReadScope(is_platform=False, tenant_id=None))


# -- crosswalk: ONE source for display AND filter (the no-drift principle) ----------


def test_every_db_stage_forward_maps() -> None:
    # No KeyError -> every live CHECK member is covered; a new member would fail loud.
    assert {stage_to_wire(stage) for stage in _ALL_DB_STAGES} == set(_ALL_WIRE_STAGES)


def test_four_screen_buttons_map_one_to_one() -> None:
    assert stage_to_wire("PRE_MAPPING_VALIDATION") == "source-shape"
    assert stage_to_wire("POST_MAPPING_VALIDATION") == "canonical-shape"
    assert stage_to_wire("IDENTITY_VALIDATION") == "fk"
    assert stage_to_wire("MAPPING_EXECUTION") == "normalization"


def test_other_bucket_collects_the_leftovers_not_drops_them() -> None:
    leftovers = {"CANONICAL_WRITE", "OTHER", "PRE_INGEST_PII", "BRONZE_WRITE", "MAPPING_LOOKUP"}
    assert {stage_to_wire(stage) for stage in leftovers} == {"other"}
    # The reverse (filter) side is the EXACT inverse of the forward (display) side.
    assert set(stage_db_values_for("other")) == leftovers


def test_display_and_filter_read_the_same_crosswalk() -> None:
    # For every wire bucket, the filter's reverse set is exactly the DB stages that
    # forward-map to it: display and filter cannot drift.
    for wire in _ALL_WIRE_STAGES:
        assert set(stage_db_values_for(wire)) == {s for s in _ALL_DB_STAGES if stage_to_wire(s) == wire}


def test_status_crosswalk() -> None:
    assert status_to_wire("NEW") == "open"
    assert status_to_wire("RESOLVED") == "resolved"
    assert status_to_wire("DISMISSED") == "resolved"
    assert status_db_values_for("open") == ["NEW"]
    assert set(status_db_values_for("resolved")) == {"RESOLVED", "DISMISSED"}


def test_unknown_db_member_fails_loud() -> None:
    with pytest.raises(KeyError):
        stage_to_wire("SOME_NEW_STAGE")
    with pytest.raises(KeyError):
        status_to_wire("ARCHIVED")


# -- Context composition (from the row's own failure_context, no second store) ------


def test_context_from_chunk_failure_message() -> None:
    ctx = _compose_context("other", {"failure_message": "mapping config invalid"})
    assert ctx == "other: mapping config invalid"


def test_context_from_row_failures_list() -> None:
    ctx = _compose_context(
        "canonical-shape",
        {"failures": [{"column": "price", "check": "numeric", "reason": "not a number"}]},
    )
    assert ctx.startswith("canonical-shape: ")
    assert "price" in ctx and "numeric" in ctx and "not a number" in ctx


def test_context_falls_back_to_stage_when_empty() -> None:
    assert _compose_context("fk", None) == "fk"
    assert _compose_context("fk", {}) == "fk"


# -- type-tagged id parse -----------------------------------------------------------


def test_parse_item_id_valid() -> None:
    kind, uid = _parse_item_id("row:0190ac0e-1a01-7001-8a01-000000000001")
    assert kind == "row"
    assert str(uid) == "0190ac0e-1a01-7001-8a01-000000000001"
    kind2, _ = _parse_item_id("chunk:0190ac0e-1a01-7001-8a01-000000000002")
    assert kind2 == "chunk"


@pytest.mark.parametrize(
    "bad", ["notatag", "row:not-a-uuid", "bogus:0190ac0e-1a01-7001-8a01-000000000001", ""]
)
def test_parse_item_id_rejects_malformed(bad: str) -> None:
    from dis_core.errors import ResourceNotFoundError

    with pytest.raises(ResourceNotFoundError):
        _parse_item_id(bad)


def test_iso_renders_utc_as_z() -> None:
    assert _iso(datetime(2026, 6, 3, 9, 8, 0, tzinfo=UTC)) == "2026-06-03T09:08:00Z"


# -- structured failures[] (detail), typed check+reason-only-required ---------------


def test_to_failures_builds_typed_list_across_all_three_shapes() -> None:
    # AC4/AC1: only check + reason are required; a structural element keeps ONLY those,
    # a value-level element adds value/column/row_index, a mapping element adds the three
    # mapping fields. Absent optional keys stay None (omitted upstream, not fabricated).
    failures = _to_failures(
        {
            "failures": [
                {"check": "not_nullable", "reason": "null in mandatory column"},  # structural
                {"check": "numeric", "reason": "nan", "column": "price", "row_index": 1, "value": "abc"},
                {
                    "check": "cast:qty",
                    "reason": "cast failed",
                    "column": "qty",
                    "row_index": 2,
                    "value": "xyz",
                    "source_column": "quantity",
                    "expected_format": "int",
                    "transform_index": 0,
                },
            ]
        }
    )
    assert len(failures) == 3
    structural, value_level, mapping = failures
    # structural: every optional field is None
    assert structural.check == "not_nullable" and structural.reason == "null in mandatory column"
    assert structural.value is None and structural.column is None and structural.source_column is None
    assert structural.expected_format is None and structural.transform_index is None
    # value-level: value/column present, mapping fields absent
    assert value_level.value == "abc" and value_level.column == "price" and value_level.row_index == 1
    assert value_level.source_column is None and value_level.expected_format is None
    # mapping cell: all three mapping fields present (transform_index=0 survives)
    assert mapping.source_column == "quantity" and mapping.expected_format == "int"
    assert mapping.transform_index == 0 and mapping.value == "xyz"


def test_to_failures_is_defensive_never_a_500() -> None:
    # No failure_context, wrong types, non-dict elements, and elements missing a required
    # field are all skipped — the detail path must not 500 on odd JSON.
    assert _to_failures(None) == []
    assert _to_failures({}) == []
    assert _to_failures({"failures": "not-a-list"}) == []
    kept = _to_failures(
        {
            "failures": [
                {"reason": "no check"},
                {"check": "no reason"},
                "not-a-dict",
                42,
                {"check": "ok", "reason": "kept"},
            ]
        }
    )
    assert len(kept) == 1 and kept[0].check == "ok" and kept[0].reason == "kept"


def test_error_context_string_is_unchanged_alongside_structured_failures() -> None:
    # AC4: the flattened error_context string is byte-identical to today's _compose_context
    # output, produced from the SAME failure_context the structured failures[] reads — the
    # structured list is ADDITIVE, never a replacement.
    fc = {"failures": [{"column": "price", "check": "numeric", "reason": "not a number"}]}
    assert _compose_context("canonical-shape", fc) == "canonical-shape: price, numeric, not a number"
    assert _to_failures(fc)[0].value is None  # the same source also yields the typed shape


# -- the wire is ADDITIVE-ONLY (nothing renamed/removed) ----------------------------


def test_quarantine_response_shape_is_additive_only() -> None:
    # Every long-standing field name still exists on both models (none renamed/removed);
    # the slice only GROWS the shape. The frontend is not updated in lockstep, so this is
    # the load-bearing wire guard.
    pre_52b_list = {
        "id",
        "kind",
        "trace_id",
        "source_id",
        "source",
        "error_reason",
        "failure_stage",
        "failed_at",
        "status",
    }
    pre_52b_detail = {
        "id",
        "kind",
        "trace_id",
        "source",
        "failed_at",
        "mapping_version",
        "error_reason",
        "failure_stage",
        "error_context",
        "original_payload",
        "chain_depth",
    }
    assert pre_52b_list <= set(QuarantineListRow.model_fields), "a pre-52b list field was renamed/removed"
    assert pre_52b_detail <= set(QuarantineDetail.model_fields), "a pre-52b detail field was renamed/removed"
    # The additive 52b fields are present.
    assert {"store_id", "store_name"} <= set(QuarantineListRow.model_fields)
    assert {"store_id", "store_name", "failures"} <= set(QuarantineDetail.model_fields)


# -- WIRE: behaviour that resolves before any DB call -------------------------------


def test_list_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/quarantine")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_token"


def test_list_denies_platform_without_ops(client: TestClient, mint_token: Callable[..., str]) -> None:
    # GET /quarantine serves a PLATFORM+dis:ops token (see-all, integration
    # suite); a PLATFORM token WITHOUT dis:ops is denied see-all -- a clean 403.
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:read",))
    response = client.get("/api/v1/quarantine", headers=_bearer(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ops_role_required"


@pytest.mark.parametrize(
    "query",
    ["status=bogus", "error_type=bogus", "window=bogus", "window=48h", "error_type=PRE_MAPPING_VALIDATION"],
)
def test_list_rejects_bad_filter_values(
    client: TestClient, mint_token: Callable[..., str], query: str
) -> None:
    # error_type takes the WIRE value (source-shape), never the DB enum - so the raw
    # DB member is a 422 too, proving DB vocab cannot leak in through the filter.
    response = client.get(f"/api/v1/quarantine?{query}", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation"


@pytest.mark.parametrize(
    "bad_id", ["notatag", "row:not-a-uuid", "bogus:0190ac0e-1a01-7001-8a01-000000000001"]
)
def test_detail_malformed_id_is_404_before_any_db_call(
    client: TestClient, mint_token: Callable[..., str], bad_id: str
) -> None:
    # The DB is unreachable in unit; a 404 here proves the parse rejects BEFORE the read.
    response = client.get(f"/api/v1/quarantine/{bad_id}", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource_not_found"


def test_detail_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/quarantine/row:0190ac0e-1a01-7001-8a01-000000000001")
    assert response.status_code == 401


def _fake_quarantine_row(**overrides: Any) -> Any:
    """A stand-in for the quarantine list Row (the _LIST_COLUMNS projection + kind + store_name)."""
    base: dict[str, Any] = {
        "kind": "row",
        "id": UUID("0190ac0e-1a01-7001-8a01-000000000001"),
        "trace_id": UUID("0190ac0e-1a01-7001-8a01-0000000000aa"),
        "tenant_id": UUID("0190ac0e-1a01-7001-8a01-0000000000dd"),
        "tenant_name": "Buc-ees",  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN)
        "source_id": "manual_csv_upload",
        "store_id": None,
        "store_name": None,
        "failure_reason": "SCHEMA_INVALID",
        "failure_stage": "PRE_MAPPING_VALIDATION",
        "quarantined_at": datetime(2026, 6, 9, 9, 12, 0, tzinfo=UTC),
        "status": "NEW",
    }
    base.update(overrides)
    return SimpleNamespace(**base)


def test_to_list_row_projects_tenant_id_and_attributes_cross_tenant() -> None:
    # Chunk 1: the quarantine list row carries its owning tenant (quarantine.*.tenant_id, NOT NULL).
    a = _to_list_row(_fake_quarantine_row())
    assert a.tenant_id == "0190ac0e-1a01-7001-8a01-0000000000dd"
    # Cross-tenant attribution across a PLATFORM see-all page.
    b = _to_list_row(_fake_quarantine_row(tenant_id=UUID("0190ac0e-1a01-7001-8a01-0000000000ee")))
    assert a.tenant_id != b.tenant_id
    # Chunk 9: tenant_name maps through; LEFT-JOIN-null (unmirrored tenant) → null, row still returned.
    assert a.tenant_name == "Buc-ees"
    null_wire = _to_list_row(_fake_quarantine_row(tenant_name=None))
    assert null_wire.tenant_name is None
    assert null_wire.tenant_id == "0190ac0e-1a01-7001-8a01-0000000000dd"
