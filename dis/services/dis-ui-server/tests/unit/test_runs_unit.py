"""Unit tests for the Ingestion Runs endpoint (GET /runs), audit-derived run state.

Three halves. PURE: the single verdict crosswalk (fail-loud on an unmapped terminal-marking
pair; precedence order) and the ISO rendering and the tenant predicate discipline. STRUCTURAL:
the anti-drift guarantee — the SQL terminal-marking predicate / verdict CASE are GENERATED from
the SAME ``TERMINAL_CROSSWALK`` tuple the Python ``verdict_of`` reads, so they cannot drift; the
test fails if either stops reading the shared source. WIRE: auth/scope (401/403), filter
validation (422), and the handler's mapping of a wide (bronze + audit-lateral + names) row to the
wire (verdict, path-aware accepted, one-bucket quarantined, names, file_name, seen_before,
completed_at, PII absent). DB-backed behaviour (isolation, ordering, the bound, the real audit
join) is the integration suite's job.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import and_, column, literal, or_
from sqlalchemy.dialects import postgresql

from dis_core.errors import InvalidCursorError, TenantScopeError
from dis_core.ids import new_uuid7
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.handlers.runs import _RUNS_PAGE_DEFAULT, _RUNS_PAGE_MAX, _iso, _to_row
from dis_ui_server.pagination import Boundary, decode_cursor, encode_cursor
from dis_ui_server.repos.runs import _keyset_term, _tenant_term, _terminal_predicate, _verdict_case
from dis_ui_server.schemas.runs import CATALOGUE_TABLE, TERMINAL_CROSSWALK, verdict_of

# Re-declared locally (the unit suite's convention: no tests package, importlib mode).
TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fake_row(**overrides: Any) -> Any:
    """A stand-in for the wide runs Row (bronze cols + audit-lateral cols + name joins)."""
    base: dict[str, Any] = {
        # bronze identity / metadata
        "id": UUID("0190ac0e-1a01-7001-8a01-000000000001"),
        "trace_id": UUID("0190ac0e-1a01-7001-8a01-0000000000aa"),
        "tenant_id": UUID("0190ac0e-1a01-7001-8a01-0000000000dd"),
        "store_id": UUID("0190ac0e-1a01-7001-8a01-0000000000bb"),
        "source_id": "manual_csv_upload",
        "dis_channel": "csv_upload",
        "source_payload_id": "us_ab12cd34ef56",
        "row_count": 1247,  # bronze total (worker DuckDB preflight)
        "template_id": UUID("0190ac0e-1a01-7001-8a01-0000000000cc"),
        "original_filename": "june-sales.csv",
        "received_at": datetime(2026, 6, 9, 9, 12, 0, tzinfo=UTC),
        "published_at": datetime(2026, 6, 9, 9, 12, 1, tzinfo=UTC),
        # display-name joins
        "tenant_name": "Buc-ees",  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN)
        "store_name": "Buc-ees #1",
        "source_name": "Manual CSV Upload",
        "template_name": "sales",
        # audit terminal lateral (event-path succeeded by default)
        "t_stage": "CANONICAL_WRITTEN",
        "t_outcome": "SUCCESS",
        "t_completed_at": datetime(2026, 6, 9, 9, 12, 6, tzinfo=UTC),
        "t_rows_succeeded": 1247,
        "t_row_count": 1247,
        "t_event_data": {"written_to_table": "canonical.store_sku_sale_events"},
        "t_mapping_version": 7,
        "seen_before": False,
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# -- PURE: the verdict crosswalk (ONE source; fail-loud; precedence) -----------------


def test_verdict_of_maps_every_crosswalk_rule() -> None:
    for stage, outcome, verdict in TERMINAL_CROSSWALK:
        probe_stage = stage if stage is not None else "ANY_STAGE_FOR_FAILURE"
        assert verdict_of(probe_stage, outcome) == verdict


def test_failure_maps_from_any_stage() -> None:
    # The (None, FAILURE) wildcard: a FAILURE at any stage is 'failed'.
    for stage in ("PRE_MAPPING_VALIDATED", "MAPPING_EXECUTED", "CANONICAL_WRITTEN", "MAPPING_LOOKED_UP"):
        assert verdict_of(stage, "FAILURE") == "failed"


def test_quarantine_success_is_quarantined_not_succeeded() -> None:
    # The load-bearing case: QUARANTINED is recorded with outcome=SUCCESS; keyed on the PAIR.
    assert verdict_of("QUARANTINED", "SUCCESS") == "quarantined"
    assert verdict_of("CANONICAL_WRITTEN", "SUCCESS") == "succeeded"


def test_verdict_of_fails_loud_on_unmapped_pair() -> None:
    # A genuinely-new terminal outcome/stage must fail loud, never guess a verdict.
    with pytest.raises(KeyError):
        verdict_of("CANONICAL_WRITTEN", "PARTIAL")
    with pytest.raises(KeyError):
        verdict_of("SOME_NEW_STAGE", "SUCCESS")


def test_iso_renders_utc_as_z() -> None:
    assert _iso(datetime(2026, 6, 3, 9, 8, 0, tzinfo=UTC)) == "2026-06-03T09:08:00Z"


# -- STRUCTURAL: the SQL and the Python crosswalk cannot drift (both generated) ------


def _compiled(expr: Any) -> str:
    compiled = expr.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})  # type: ignore[no-untyped-call]
    return str(compiled)


def test_sql_verdict_case_is_generated_from_the_same_crosswalk() -> None:
    """The SQL verdict CASE and the Python verdict_of read ONE source (TERMINAL_CROSSWALK).

    Fails if either drifts: (1) the compiled CASE has exactly one WHEN per crosswalk rule; (2)
    every rule's literals (stage, outcome, verdict) appear in the compiled SQL; (3) for every
    rule, verdict_of agrees with the rule. A hand-edited SQL branch not in the crosswalk, or a
    changed verdict_of, breaks one of these.
    """
    sql = _compiled(_verdict_case(column("stage"), column("outcome")))
    assert sql.count("WHEN") == len(TERMINAL_CROSSWALK)
    for stage, outcome, verdict in TERMINAL_CROSSWALK:
        assert outcome in sql and verdict in sql
        if stage is not None:
            assert stage in sql
        probe_stage = stage if stage is not None else "ANY_STAGE"
        assert verdict_of(probe_stage, outcome) == verdict


def test_sql_terminal_predicate_covers_every_crosswalk_rule() -> None:
    sql = _compiled(_terminal_predicate(column("stage"), column("outcome")))
    for stage, outcome, _verdict in TERMINAL_CROSSWALK:
        assert outcome in sql
        if stage is not None:
            assert stage in sql


# -- PURE: tenant predicate is conditional on PLATFORM, never on tenant-absence ------


def test_tenant_term_conditional_on_platform() -> None:
    pinned = _tenant_term(ReadScope(is_platform=False, tenant_id=new_uuid7()))
    assert any("tenant_id" in str(term) for term in pinned), "pinned (TENANT) scope lost its predicate"
    platform = _tenant_term(ReadScope(is_platform=True, tenant_id=None))
    assert not any("tenant_id" in str(term) for term in platform), "PLATFORM see-all still pins a tenant"


def test_tenant_term_refuses_a_pinned_scope_without_a_tenant() -> None:
    with pytest.raises(TenantScopeError):
        _tenant_term(ReadScope(is_platform=False, tenant_id=None))


# -- PURE: the row -> wire mapper (verdict, counts, names, file_name, PII absent) -----


def test_to_row_succeeded_event_path() -> None:
    wire = _to_row(_fake_row())
    assert wire.status == "succeeded"  # audit-derived verdict
    assert wire.method == "csv_upload"
    assert wire.mapping_version == 7  # from the terminal audit event
    assert wire.input_row_count == 1247  # bronze total
    assert wire.accepted == 1247  # event path: rows_succeeded
    assert wire.quarantined == 0  # succeeded -> no quarantine bucket
    assert wire.completed_at == "2026-06-09T09:12:06Z"
    assert wire.store_name == "Buc-ees #1" and wire.source_name == "Manual CSV Upload"
    assert wire.template_name == "sales" and wire.file_name == "june-sales.csv"
    assert wire.seen_before is False
    dumped = wire.model_dump()
    for pii in ("auth_principal", "client_ip", "user_agent", "gcs_uri"):
        assert pii not in dumped
    assert "dis_channel" not in dumped and "mapping_version_id" not in dumped
    assert "last_updated_at" not in dumped  # deliberately not served


def test_to_row_succeeded_catalogue_path_reads_event_data() -> None:
    # Snapshot/catalogue path: rows_succeeded is 0; accepted = hot_rows_upserted + hot_noops.
    wire = _to_row(
        _fake_row(
            t_rows_succeeded=0,
            t_event_data={"written_to_table": CATALOGUE_TABLE, "hot_rows_upserted": 3, "hot_noops": 2},
        )
    )
    assert wire.status == "succeeded"
    assert wire.accepted == 5  # 3 upserts + 2 older-event noops (guards the rows_succeeded=0 trap)
    assert wire.quarantined == 0


def test_to_row_quarantined_bucket_and_zero_accepted() -> None:
    wire = _to_row(_fake_row(t_stage="QUARANTINED", t_outcome="SUCCESS", t_row_count=1247))
    assert wire.status == "quarantined"
    assert wire.accepted == 0
    assert wire.quarantined == 1247  # the one bucket = the QUARANTINED event's row_count


def test_to_row_failed_leaves_quarantined_null() -> None:
    wire = _to_row(_fake_row(t_stage="MAPPING_EXECUTED", t_outcome="FAILURE"))
    assert wire.status == "failed"
    assert wire.accepted == 0
    assert wire.quarantined is None  # a pure nack is not held; cell-grain rows_failed not surfaced


def test_to_row_processing_when_no_terminal_event() -> None:
    wire = _to_row(_fake_row(t_stage=None, t_outcome=None, t_completed_at=None, t_mapping_version=None))
    assert wire.status == "processing"
    assert wire.accepted is None and wire.quarantined is None
    assert wire.completed_at is None and wire.mapping_version is None


def test_to_row_absent_names_and_store_tolerated() -> None:
    wire = _to_row(
        _fake_row(
            store_id=None,
            store_name=None,
            source_name=None,
            template_id=None,
            template_name=None,
            original_filename=None,
            published_at=None,
        )
    )
    assert wire.store_id is None and wire.store_name is None
    assert wire.source_name is None and wire.template_id is None and wire.template_name is None
    assert wire.file_name is None and wire.published_at is None


def test_to_row_seen_before_true() -> None:
    assert _to_row(_fake_row(seen_before=True)).seen_before is True


# -- WIRE: behaviour that resolves before / around the DB call -----------------------


def test_list_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/runs")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_token"


def test_list_denies_platform_without_ops(client: TestClient, mint_token: Callable[..., str]) -> None:
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:read",))
    response = client.get("/api/v1/runs", headers=_bearer(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ops_role_required"


@pytest.mark.parametrize("query", ["status=bogus", "status=PROCESSED", "window=bogus", "window=48h"])
def test_list_rejects_bad_filter_values(
    client: TestClient, mint_token: Callable[..., str], query: str
) -> None:
    # status takes the WIRE verdict (succeeded), never a DB enum — the raw member is a 422 too.
    response = client.get(f"/api/v1/runs?{query}", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "request_validation"


def test_list_maps_repo_rows_to_wire(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_list(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [_fake_row(t_event_data={"written_to_table": "canonical.store_sku_sale_events"})]

    monkeypatch.setattr("dis_ui_server.handlers.runs.list_runs", _fake_list)
    resp = client.get("/api/v1/runs", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["status"] == "succeeded"
    assert item["accepted"] == 1247 and item["quarantined"] == 0 and item["input_row_count"] == 1247
    assert item["store_name"] == "Buc-ees #1" and item["file_name"] == "june-sales.csv"
    assert item["seen_before"] is False
    for pii in ("auth_principal", "client_ip", "user_agent", "gcs_uri"):
        assert pii not in item


def test_filters_pass_through_to_repo(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _capture(*_args: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr("dis_ui_server.handlers.runs.list_runs", _capture)
    resp = client.get(
        "/api/v1/runs?status=quarantined&window=24h", headers=_bearer(mint_token(tenant_id=TENANT_A))
    )
    assert resp.status_code == 200
    # status is the wire verdict, passed straight through (the repo filters the derived verdict).
    assert captured["status"] == "quarantined"
    assert isinstance(captured["window_cutoff"], datetime)
    assert captured["limit"] == _RUNS_PAGE_DEFAULT


def test_no_filters_pass_none(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _capture(*_args: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr("dis_ui_server.handlers.runs.list_runs", _capture)
    resp = client.get("/api/v1/runs", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    assert captured["status"] is None
    assert captured["window_cutoff"] is None
    assert captured["limit"] == _RUNS_PAGE_DEFAULT
    assert captured["after"] is None  # no cursor -> no keyset boundary


# -- pagination: page size, next-cursor, opaque cursor, cross-filter ------------------------

_B = Boundary(
    received_at=datetime(2026, 6, 9, 9, 12, 0, tzinfo=UTC),
    id=UUID("0190ac0e-1a01-7001-8a01-000000000001"),
)


def _fake_list(n: int) -> Callable[..., Any]:
    async def _inner(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [_fake_row() for _ in range(n)]

    return _inner


def test_next_cursor_present_on_overfetch_absent_on_last_page(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # AC1: repo over-fetches (limit + 1) -> a next page exists -> next_cursor set, page trimmed.
    monkeypatch.setattr("dis_ui_server.handlers.runs.list_runs", _fake_list(3))
    resp = client.get("/api/v1/runs?limit=2", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["items"]) == 2 and body["next_cursor"] is not None
    # AC1: exactly `limit` rows back (no over-fetch) -> last page -> next_cursor null.
    monkeypatch.setattr("dis_ui_server.handlers.runs.list_runs", _fake_list(2))
    resp = client.get("/api/v1/runs?limit=2", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.json()["next_cursor"] is None


def test_limit_default_explicit_and_clamped(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    # AC3: default applies; an explicit value passes; an over-max value is CLAMPED, never unbounded.
    captured: dict[str, Any] = {}

    async def _cap(*_args: Any, **kwargs: Any) -> list[Any]:
        captured.clear()
        captured.update(kwargs)
        return []

    monkeypatch.setattr("dis_ui_server.handlers.runs.list_runs", _cap)
    headers = _bearer(mint_token(tenant_id=TENANT_A))
    client.get("/api/v1/runs", headers=headers)
    assert captured["limit"] == _RUNS_PAGE_DEFAULT
    client.get("/api/v1/runs?limit=10", headers=headers)
    assert captured["limit"] == 10
    client.get(f"/api/v1/runs?limit={_RUNS_PAGE_MAX + 5000}", headers=headers)
    assert captured["limit"] == _RUNS_PAGE_MAX  # clamped to the hard ceiling


@pytest.mark.parametrize("bad", ["limit=0", "limit=-1", "limit=abc"])
def test_limit_rejects_below_one_and_non_int(
    client: TestClient, mint_token: Callable[..., str], bad: str
) -> None:
    # AC3: <1 / non-int is a 422 (Query ge=1) — same posture as the status/window filters.
    resp = client.get(f"/api/v1/runs?{bad}", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "request_validation"


def test_cursor_round_trips_and_is_opaque() -> None:
    # AC4: encode/decode round-trip; the token exposes neither the raw id nor the timestamp.
    token = encode_cursor(_B, status="succeeded", window="7d")
    assert decode_cursor(token, status="succeeded", window="7d") == _B
    assert str(_B.id) not in token and "2026-06-09" not in token


def test_cursor_undecodable_raises_invalid_cursor() -> None:
    with pytest.raises(InvalidCursorError):
        decode_cursor("not*a*valid*cursor", status=None, window=None)


def test_cursor_endpoint_garbage_is_422_invalid_cursor(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("dis_ui_server.handlers.runs.list_runs", _fake_list(0))
    resp = client.get(
        "/api/v1/runs?cursor=not*a*valid*cursor", headers=_bearer(mint_token(tenant_id=TENANT_A))
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_cursor"


def test_cursor_filter_mismatch_raises() -> None:
    # AC5: a cursor is valid only within its issuing filter set; a different one is rejected.
    token = encode_cursor(_B, status="succeeded", window=None)
    with pytest.raises(InvalidCursorError):
        decode_cursor(token, status="quarantined", window=None)  # status changed
    with pytest.raises(InvalidCursorError):
        decode_cursor(token, status="succeeded", window="24h")  # window changed
    assert decode_cursor(token, status="succeeded", window=None) == _B  # same set decodes


def test_cursor_filter_mismatch_via_endpoint_is_422(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr("dis_ui_server.handlers.runs.list_runs", _fake_list(0))
    token = encode_cursor(_B, status="succeeded", window=None)
    resp = client.get(
        f"/api/v1/runs?status=quarantined&cursor={token}", headers=_bearer(mint_token(tenant_id=TENANT_A))
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "invalid_cursor"


# -- regression guard: the keyset predicate MUST stay the row-value form ---------------------


def _passes_keyset_guard(sql: str) -> bool:
    """The index-pushable ROW-VALUE form is a tuple comparison with NO OR-expansion."""
    return ") < (" in sql and " OR " not in sql


def test_keyset_predicate_is_row_value_not_or_expanded() -> None:
    """The keyset boundary MUST compile to the row-value tuple comparison ``(received_at, id) <
    (:r, :i)`` — the form the live EXPLAIN proved is pushed into the composite index as a true
    seek. The OR-expanded equivalent is NOT index-pushed (offset-like scan) and is forbidden.

    This FAILS if ``_keyset_term`` is ever rewritten to the OR form — proven by the second
    assertion, which shows the guard rejects that exact OR form.
    """
    keyset_sql = _compiled(_keyset_term(_B))
    assert _passes_keyset_guard(keyset_sql), f"keyset predicate is not the row-value form: {keyset_sql}"
    # Discriminator: the forbidden OR-expanded equivalent does NOT pass the guard.
    or_form = _compiled(
        or_(
            column("received_at") < literal(_B.received_at),
            and_(column("received_at") == literal(_B.received_at), column("id") < literal(_B.id)),
        )
    )
    assert not _passes_keyset_guard(or_form), f"guard failed to reject the OR-expanded form: {or_form}"


def test_to_row_projects_tenant_id_and_attributes_cross_tenant() -> None:
    # Chunk 1: the run row now carries its owning tenant (bronze.tenant_id, NOT NULL).
    a = _to_row(_fake_row(tenant_id=UUID("0190ac0e-1a01-7001-8a01-0000000000dd")))
    assert a.tenant_id == "0190ac0e-1a01-7001-8a01-0000000000dd"
    # Cross-tenant attribution: a PLATFORM see-all page carries rows with DIFFERENT tenant_ids.
    b = _to_row(_fake_row(tenant_id=UUID("0190ac0e-1a01-7001-8a01-0000000000ee")))
    assert a.tenant_id != b.tenant_id
    # Chunk 9: tenant_name maps through (a real name, not the UUID); LEFT-JOIN-null (unmirrored
    # tenant) → null name, and the row is still returned intact.
    assert a.tenant_name == "Buc-ees"
    null_wire = _to_row(_fake_row(tenant_name=None))
    assert null_wire.tenant_name is None
    assert null_wire.tenant_id == "0190ac0e-1a01-7001-8a01-0000000000dd"
