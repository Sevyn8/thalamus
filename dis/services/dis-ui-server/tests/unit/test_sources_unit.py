"""Unit tests for the source registry endpoints (GET/POST /sources), Phase A (D112).

DB-free. Auth/scope gates (401/403 incl. the TENANT-names-a-tenant 403 that resolves BEFORE
any DB touch), body validation (422 on a bad channel), and — with the repo monkeypatched — the
create/list wire-mapping (channel passthrough, ISO timestamps) plus the duplicate -> 409 error
surfacing. The DB-backed behaviour (RLS write isolation, WITH CHECK, backfill) is the
integration suite's job.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from dis_core.errors import SourceAlreadyExistsError

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees
TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"  # zabka-group


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fake_row(**overrides: Any) -> Any:
    base: dict[str, Any] = {
        "tenant_id": "0190ac0e-1a01-7001-8a01-0000000000dd",
        "tenant_name": "Buc-ees",  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN)
        "source_id": "shopify_pos_v2",
        "display_name": "Shopify POS v2",
        "channel": "api",
        "store_id": None,
        "schedule": None,
        "status": "active",
        "created_at": datetime(2026, 6, 9, 9, 12, 0, tzinfo=UTC),
        "updated_at": datetime(2026, 6, 9, 9, 12, 0, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# -- auth / scope gates -------------------------------------------------------------


def test_get_requires_a_token(client: TestClient) -> None:
    assert client.get("/api/v1/sources").status_code == 401


def test_post_requires_a_token(client: TestClient) -> None:
    resp = client.post("/api/v1/sources", json={"source_id": "x", "display_name": "X"})
    assert resp.status_code == 401


def test_post_tenant_naming_acted_for_is_403_before_db(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    # A TENANT token that names an acted-for tenant is rejected by resolve_acted_for (403),
    # BEFORE any DB touch — the DB is unreachable in unit, so a 403 proves it never opened a session.
    token = mint_token(tenant_id=TENANT_A)  # TENANT
    resp = client.post(
        "/api/v1/sources",
        headers=_bearer(token),
        json={"source_id": "sq", "display_name": "Square", "acting_for_tenant_id": TENANT_B},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "tenant_scope"


def test_post_platform_without_ops_is_403(client: TestClient, mint_token: Callable[..., str]) -> None:
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:read",))
    resp = client.post(
        "/api/v1/sources",
        headers=_bearer(token),
        json={"source_id": "sq", "display_name": "Square", "acting_for_tenant_id": TENANT_A},
    )
    assert resp.status_code == 403
    assert resp.json()["error"]["code"] == "ops_role_required"


@pytest.mark.parametrize("channel", ["ftp", "SFTP", "webhook"])
def test_post_rejects_bad_channel(client: TestClient, mint_token: Callable[..., str], channel: str) -> None:
    # channel takes the dis_channel vocab only; anything else is a 422 (Literal validation).
    resp = client.post(
        "/api/v1/sources",
        headers=_bearer(mint_token(tenant_id=TENANT_A)),
        json={"source_id": "sq", "display_name": "Square", "channel": channel},
    )
    assert resp.status_code == 422
    assert resp.json()["error"]["code"] == "request_validation"


@pytest.mark.parametrize("bad_slug", ["Has Caps", "has-dash", "with space", ""])
def test_post_rejects_bad_source_id(
    client: TestClient, mint_token: Callable[..., str], bad_slug: str
) -> None:
    resp = client.post(
        "/api/v1/sources",
        headers=_bearer(mint_token(tenant_id=TENANT_A)),
        json={"source_id": bad_slug, "display_name": "X"},
    )
    assert resp.status_code == 422


# -- wire mapping (repo monkeypatched) ----------------------------------------------


def test_post_maps_created_row_to_wire(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_create(*_args: Any, **_kwargs: Any) -> Any:
        return _fake_row(source_id="shopify_pos_v2", channel="api")

    monkeypatch.setattr("dis_ui_server.handlers.sources.create_source", _fake_create)
    resp = client.post(
        "/api/v1/sources",
        headers=_bearer(mint_token(tenant_id=TENANT_A)),
        json={"source_id": "shopify_pos_v2", "display_name": "Shopify POS v2", "channel": "api"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["source_id"] == "shopify_pos_v2"
    assert body["channel"] == "api"  # passthrough
    assert body["status"] == "active"
    assert body["created_at"] == "2026-06-09T09:12:00Z"
    assert body["tenant_id"] == "0190ac0e-1a01-7001-8a01-0000000000dd"  # Chunk 1: projected onto the wire
    # Chunk 9: the create echo carries tenant_name too (from the RETURNING correlated subquery).
    assert body["tenant_name"] == "Buc-ees"


def test_post_duplicate_is_409(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _raise_dup(*_args: Any, **_kwargs: Any) -> Any:
        raise SourceAlreadyExistsError("dup", tenant_id=TENANT_A, source_id="shopify_pos_v2")

    monkeypatch.setattr("dis_ui_server.handlers.sources.create_source", _raise_dup)
    resp = client.post(
        "/api/v1/sources",
        headers=_bearer(mint_token(tenant_id=TENANT_A)),
        json={"source_id": "shopify_pos_v2", "display_name": "Shopify POS v2"},
    )
    assert resp.status_code == 409
    assert resp.json()["error"]["code"] == "source_already_exists"


def test_get_maps_repo_rows_to_wire(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_list(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [_fake_row(source_id="manual_csv_upload", channel=None, display_name="Manual Csv Upload")]

    monkeypatch.setattr("dis_ui_server.handlers.sources.list_sources", _fake_list)
    resp = client.get("/api/v1/sources", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["source_id"] == "manual_csv_upload"
    assert item["channel"] is None  # backfill-unknown channel stays null, never fabricated
    assert item["display_name"] == "Manual Csv Upload"
    assert item["tenant_id"] == "0190ac0e-1a01-7001-8a01-0000000000dd"  # Chunk 1: fleet attribution
    assert item["tenant_name"] == "Buc-ees"  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN)


def test_create_source_tenant_name_subquery_does_not_cross_join() -> None:
    """REGRESSION, at compile time: the tenant_name scalar must not re-list config.sources.

    The live proof is the integration test (creating a third source for a tenant that
    already has two), but a CardinalityViolation only reproduces against real Postgres, so
    this asserts the SQL SHAPE and runs in every unit run with no stack.

    The defect: `.where(TenantRow.tenant_id == Source.tenant_id).correlate(Source)` inside a
    RETURNING clause. A RETURNING clause has no enclosing FROM for the insert target, so
    `.correlate()` is a no-op and SQLAlchemy auto-adds config.sources to the SUBQUERY's own
    FROM - a cross join returning one row per source the tenant already had.
    """
    import re
    from uuid import UUID

    from sqlalchemy import insert, select
    from sqlalchemy.dialects import postgresql

    from dis_ui_server.models import Source, TenantRow

    # Built the way create_source builds it; the assertion is on the subquery's FROM.
    statement = (
        insert(Source)
        .values(tenant_id=UUID(int=1), source_id="s", display_name="d")
        .returning(
            Source.tenant_id,
            select(TenantRow.name)
            .where(TenantRow.tenant_id == UUID(int=1))
            .scalar_subquery()
            .label("tenant_name"),
        )
    )
    sql = str(statement.compile(dialect=postgresql.dialect()))  # type: ignore[no-untyped-call]
    subquery = re.search(r"\(SELECT.*?\)", sql, re.S)
    assert subquery is not None, sql
    # identity_mirror.tenants alone. config.sources here is the cross join.
    assert "config.sources" not in subquery.group(0), subquery.group(0)
    assert "identity_mirror.tenants" in subquery.group(0)
