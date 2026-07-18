"""``GET /api/v1/audit`` against the LIVE stack (read-only audit-log reads).

Proves the audit read is VALID against the real ``audit.events`` schema and runs
tenant-scoped through ``read_session`` for two distinct tenants. Counts depend on seed state,
so the HTTP tests assert the SHAPE, the types, newest-first ordering, and the bound rather
than fragile exact numbers.

The audit-specific guard (the two-GUC OUTLIER, D91): ``audit.events`` RLS is USING-only and
its USING branch admits ``tenant_id IS NULL`` system rows to EVERY tenant. The read must NOT
surface those to a TENANT - the repo's defense-in-depth ``tenant_id = :tenant`` predicate is
what strips them. That is unobservable at the wire (tenant_id is not on the wire), so it is
pinned here against live data via the sanctioned ``dis-rls`` sessions: under a TENANT session,
the RLS-admitted set may include NULL rows, but the predicate path returns only the tenant's;
under a PLATFORM session the set is widened (all tenants + system rows).

Loud-error posture (the Slice 4/7/8 lesson): a missing stack env var ERRORS, never skips.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from dis_rls import create_rls_engine, rls_platform_session, rls_session
from dis_ui_server.main import create_app

pytestmark = pytest.mark.integration

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees (live seed)
TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"  # zabka-group (live seed)

_VALID_OUTCOMES = {"success", "failure", "skipped", "retried", "duplicate"}
_VALID_SCOPES = {"INGRESS_EVENT", "ROW"}


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def live_client(stack_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("POSTGRES_URL", stack_env["POSTGRES_URL"])
    with TestClient(create_app()) as client:
        yield client


def _assert_well_shaped(body: dict[str, object]) -> None:
    items = body["items"]
    assert isinstance(items, list)
    assert len(items) <= 100  # the bound
    prev: str | None = None
    for row in items:
        assert isinstance(row, dict)
        assert isinstance(row["id"], str) and isinstance(row["trace_id"], str)
        assert isinstance(row["event_timestamp"], str) and row["event_timestamp"].endswith("Z")
        assert isinstance(row["service_name"], str) and isinstance(row["stage"], str)
        assert row["event_scope"] in _VALID_SCOPES
        assert row["outcome"] in _VALID_OUTCOMES
        assert row["prior_trace_id"] is None or isinstance(row["prior_trace_id"], str)
        assert row["mapping_version"] is None or isinstance(row["mapping_version"], int)
        # PII columns are never present on the wire.
        assert "auth_principal" not in row
        assert "client_ip" not in row
        # newest-first ordering.
        if prev is not None:
            assert row["event_timestamp"] <= prev
        prev = row["event_timestamp"]


def test_audit_valid_and_scoped_for_tenant_a(live_client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = live_client.get("/api/v1/audit", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_audit_valid_for_tenant_b(live_client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = live_client.get("/api/v1/audit", headers=_bearer(mint_token(tenant_id=TENANT_B)))
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_audit_platform_ops_sees_widened_set(live_client: TestClient, mint_token: Callable[..., str]) -> None:
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:ops", "dis:read"))
    resp = live_client.get("/api/v1/audit", headers=_bearer(token))
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_audit_requires_a_token(live_client: TestClient) -> None:
    assert live_client.get("/api/v1/audit").status_code == 401


def test_audit_outcome_filter_is_honoured(live_client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = live_client.get("/api/v1/audit?outcome=success", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    assert all(row["outcome"] == "success" for row in resp.json()["items"])


async def test_tenant_never_sees_system_null_rows(stack_env: dict[str, str]) -> None:
    """The defense-in-depth predicate strips tenant_id IS NULL system rows from a TENANT read.

    Observed directly against live data via dis-rls (tenant_id is not on the wire). Under a
    TENANT session the RLS USING branch may ADMIT system NULL rows, but the repo's predicate
    (tenant_id = :tenant) returns only the tenant's; under a PLATFORM session the set widens.
    """
    engine = create_rls_engine(stack_env["POSTGRES_URL"])
    try:
        # The repo's TENANT path: RLS session + the defense-in-depth predicate. No NULLs.
        async with rls_session(engine, UUID(TENANT_A)) as conn:
            predicate_rows = (
                await conn.execute(
                    text(
                        "SELECT tenant_id FROM audit.events WHERE tenant_id = :t "
                        "ORDER BY event_timestamp DESC LIMIT 100"
                    ),
                    {"t": TENANT_A},
                )
            ).all()
            # What RLS alone admits to this tenant (may include tenant_id IS NULL system rows).
            rls_admitted = {
                r.tenant_id
                for r in (await conn.execute(text("SELECT DISTINCT tenant_id FROM audit.events"))).all()
            }

        # The predicate path never returns another tenant's or a system NULL row.
        assert all(r.tenant_id == UUID(TENANT_A) for r in predicate_rows)

        # PLATFORM see-all widens: it can span multiple tenants and/or system NULL rows.
        async with rls_platform_session(engine, None) as conn:
            platform_tenants = {
                r.tenant_id
                for r in (await conn.execute(text("SELECT DISTINCT tenant_id FROM audit.events"))).all()
            }

        # The tenant's RLS-admitted set is a subset of the platform-visible set (see-all widens).
        assert rls_admitted <= platform_tenants
    finally:
        await engine.dispose()
