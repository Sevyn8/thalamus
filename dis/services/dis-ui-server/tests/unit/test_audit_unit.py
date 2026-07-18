"""Unit tests for the audit event log endpoint (GET /audit).

Two halves. PURE: the single outcome crosswalk (display forward == filter reverse, no drift;
the DUPLICATE_* pair collapses to one queryable bucket), the ISO rendering, the trace_id
parse, and the tenant-predicate discipline. WIRE: the parts that resolve BEFORE any database
call - auth/scope (401/403), query-filter validation (422), a malformed trace_id (404) - and,
with the repo monkeypatched to a fixed row set, the handler's mapping of a DB row to the wire
(the outcome crosswalk, ISO timestamps, mapping_version from mapping_version_id, and the PII
columns ABSENT) plus the wire->DB filter translation. The DB-backed behaviour (isolation,
ordering, the bound, system-row exclusion) is the integration suite's job.
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
from dis_core.timestamps import now_utc
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.handlers.audit import _AUDIT_LIST_LIMIT, _iso, _parse_trace_id, _to_row
from dis_ui_server.repos.audit import _tenant_term
from dis_ui_server.schemas.audit import OutcomeWire, outcome_db_values_for, outcome_to_wire

# Re-declared locally (the unit suite's convention: no tests package, importlib mode).
TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees

# The live CHECK vocabulary (ck_audit_events_outcome_vocab). Every member MUST forward-map.
_ALL_DB_OUTCOMES = (
    "SUCCESS",
    "FAILURE",
    "SKIPPED",
    "RETRIED",
    "DUPLICATE_NOOP",
    "DUPLICATE_OVERWRITTEN",
)
_ALL_WIRE_OUTCOMES: tuple[OutcomeWire, ...] = ("success", "failure", "skipped", "retried", "duplicate")


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fake_row(**overrides: Any) -> Any:
    """A stand-in for a SQLAlchemy Row over the _LIST_COLUMNS projection (attribute access)."""
    base: dict[str, Any] = {
        "id": UUID("0190ac0e-1a01-7001-8a01-000000000001"),
        "event_timestamp": datetime(2026, 6, 9, 9, 12, 0, tzinfo=UTC),
        "trace_id": UUID("0190ac0e-1a01-7001-8a01-0000000000aa"),
        "tenant_id": UUID("0190ac0e-1a01-7001-8a01-0000000000dd"),
        "tenant_name": "Buc-ees",  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN)
        "prior_trace_id": None,
        "service_name": "csv-ingest-worker",
        "stage": "BRONZE_WRITTEN",
        "event_scope": "INGRESS_EVENT",
        "outcome": "SUCCESS",
        "row_count": 42,
        "rows_succeeded": 42,
        "rows_failed": 0,
        "duration_ms": 118,
        "mapping_version_id": 7,
        "failure_code": None,
        "failure_message": None,
        "event_data": {"gcs_uri": "gs://x/y"},
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# -- PURE: the crosswalk (ONE source for display AND filter) -------------------------


def test_every_db_outcome_forward_maps() -> None:
    # No KeyError -> every live CHECK member is covered; a new member would fail loud.
    assert {outcome_to_wire(o) for o in _ALL_DB_OUTCOMES} == set(_ALL_WIRE_OUTCOMES)


def test_duplicate_pair_collapses_to_one_bucket() -> None:
    assert outcome_to_wire("DUPLICATE_NOOP") == "duplicate"
    assert outcome_to_wire("DUPLICATE_OVERWRITTEN") == "duplicate"
    # The reverse (filter) side returns BOTH DB members - the exact inverse of display.
    assert set(outcome_db_values_for("duplicate")) == {"DUPLICATE_NOOP", "DUPLICATE_OVERWRITTEN"}


def test_display_and_filter_read_the_same_crosswalk() -> None:
    for wire in _ALL_WIRE_OUTCOMES:
        assert set(outcome_db_values_for(wire)) == {o for o in _ALL_DB_OUTCOMES if outcome_to_wire(o) == wire}


def test_unknown_db_outcome_fails_loud() -> None:
    with pytest.raises(KeyError):
        outcome_to_wire("ARCHIVED")


def test_iso_renders_utc_as_z() -> None:
    assert _iso(datetime(2026, 6, 3, 9, 8, 0, tzinfo=UTC)) == "2026-06-03T09:08:00Z"


def test_parse_trace_id_valid() -> None:
    uid = _parse_trace_id("0190ac0e-1a01-7001-8a01-0000000000aa")
    assert str(uid) == "0190ac0e-1a01-7001-8a01-0000000000aa"


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "row:0190ac0e"])
def test_parse_trace_id_rejects_malformed(bad: str) -> None:
    from dis_core.errors import ResourceNotFoundError

    with pytest.raises(ResourceNotFoundError):
        _parse_trace_id(bad)


# -- PURE: tenant predicate is conditional on PLATFORM, never on tenant-absence ------


def test_tenant_term_conditional_on_platform() -> None:
    # Pinned (TENANT) scope carries the predicate; PLATFORM see-all omits it. The predicate
    # is what excludes tenant_id IS NULL system rows from a TENANT read (the audit-specific
    # guard). Conditioned on is_platform, NEVER on tenant_id being absent.
    pinned = _tenant_term(ReadScope(is_platform=False, tenant_id=new_uuid7()))
    assert any("tenant_id" in str(term) for term in pinned), "pinned (TENANT) scope lost its tenant predicate"
    platform = _tenant_term(ReadScope(is_platform=True, tenant_id=None))
    assert not any("tenant_id" in str(term) for term in platform), "PLATFORM see-all still pins a tenant"


def test_tenant_term_refuses_a_pinned_scope_without_a_tenant() -> None:
    with pytest.raises(TenantScopeError):
        _tenant_term(ReadScope(is_platform=False, tenant_id=None))


# -- PURE: the row -> wire mapper (crosswalk, ISO, mapping_version, PII absent) ------


def test_to_row_maps_db_row_to_wire() -> None:
    wire = _to_row(_fake_row(outcome="DUPLICATE_NOOP", mapping_version_id=9))
    assert wire.outcome == "duplicate"  # forward crosswalk
    assert wire.event_timestamp == "2026-06-09T09:12:00Z"  # ISO with Z
    assert wire.mapping_version == 9  # from mapping_version_id
    # PII columns are not on the wire model at all.
    dumped = wire.model_dump()
    assert "auth_principal" not in dumped
    assert "client_ip" not in dumped
    assert "mapping_version_id" not in dumped  # renamed to mapping_version


# -- WIRE: behaviour that resolves before / around the DB call -----------------------


def test_list_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/audit")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_token"


def test_list_denies_platform_without_ops(client: TestClient, mint_token: Callable[..., str]) -> None:
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:read",))
    response = client.get("/api/v1/audit", headers=_bearer(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ops_role_required"


@pytest.mark.parametrize("query", ["outcome=bogus", "outcome=SUCCESS", "window=bogus", "window=48h"])
def test_list_rejects_bad_filter_values(
    client: TestClient, mint_token: Callable[..., str], query: str
) -> None:
    # outcome takes the WIRE value (success), never the DB enum - so the raw DB member is a
    # 422 too, proving DB vocab cannot leak in through the filter.
    response = client.get(f"/api/v1/audit?{query}", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation"


def test_list_malformed_trace_id_is_404_before_any_db_call(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    # The DB is unreachable in unit; a 404 here proves the parse rejects BEFORE the read.
    response = client.get(
        "/api/v1/audit?trace_id=not-a-uuid", headers=_bearer(mint_token(tenant_id=TENANT_A))
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource_not_found"


def test_list_maps_repo_rows_to_wire(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_list(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [_fake_row(outcome="DUPLICATE_OVERWRITTEN", mapping_version_id=3)]

    monkeypatch.setattr("dis_ui_server.handlers.audit.list_events", _fake_list)
    resp = client.get("/api/v1/audit", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["outcome"] == "duplicate"
    assert item["event_timestamp"] == "2026-06-09T09:12:00Z"
    assert item["mapping_version"] == 3
    assert item["failure_code"] is None
    assert item["event_data"] == {"gcs_uri": "gs://x/y"}
    # PII columns never reach the wire.
    assert "auth_principal" not in item
    assert "client_ip" not in item


def test_filters_translate_to_db_vocabulary(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _capture(*_args: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr("dis_ui_server.handlers.audit.list_events", _capture)
    trace = "0190ac0e-1a01-7001-8a01-0000000000aa"
    resp = client.get(
        f"/api/v1/audit?outcome=duplicate&window=24h&trace_id={trace}",
        headers=_bearer(mint_token(tenant_id=TENANT_A)),
    )
    assert resp.status_code == 200
    # outcome -> the reverse crosswalk (both DUPLICATE_* DB members).
    assert set(captured["outcomes"]) == {"DUPLICATE_NOOP", "DUPLICATE_OVERWRITTEN"}
    # window -> a cutoff ~24h before now (computed once per request).
    assert isinstance(captured["window_cutoff"], datetime)
    assert abs((now_utc() - captured["window_cutoff"]).total_seconds() - 86400) < 10
    # trace_id -> parsed UUID; the bound is applied.
    assert captured["trace_id"] == UUID(trace)
    assert captured["limit"] == _AUDIT_LIST_LIMIT


def test_no_filters_pass_none(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _capture(*_args: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr("dis_ui_server.handlers.audit.list_events", _capture)
    resp = client.get("/api/v1/audit", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    assert captured["trace_id"] is None
    assert captured["outcomes"] is None
    assert captured["window_cutoff"] is None
    assert captured["limit"] == _AUDIT_LIST_LIMIT


def test_to_row_tenant_id_is_optional_and_handles_platform_null_system_row() -> None:
    # Chunk 1: audit rows carry tenant_id; OPTIONAL because a PLATFORM see-all surfaces
    # tenant_id IS NULL system rows (the RLS OR-NULL branch) — the mapper must not error.
    real = _to_row(_fake_row(tenant_id=UUID("0190ac0e-1a01-7001-8a01-0000000000dd")))
    assert real.tenant_id == "0190ac0e-1a01-7001-8a01-0000000000dd"
    system = _to_row(_fake_row(tenant_id=None, tenant_name=None))  # NULL-tenant system row
    assert system.tenant_id is None
    # Chunk 9: a system (null-tenant) row has no tenant to name → tenant_name null (honest); a real
    # row carries the LEFT-joined name. The mapper never errors on either.
    assert system.tenant_name is None
    assert real.tenant_name == "Buc-ees"
    # A see-all page can therefore carry real tenant_ids AND a null side by side, attributed.
    other = _to_row(_fake_row(tenant_id=UUID("0190ac0e-1a01-7001-8a01-0000000000ee")))
    assert other.tenant_id != real.tenant_id
