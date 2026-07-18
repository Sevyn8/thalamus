"""Unit tests for the Canonical Explorer endpoint (GET /canonical/store-sku-positions).

DB-free. PURE: the ISO rendering, the money-safe Decimal->str, the tenant predicate discipline,
and the store-id parse. WIRE: auth/scope (401/403), a malformed store filter (404 before the DB),
and — with the repo monkeypatched to a fixed row set — the handler's mapping of a canonical row
to the wire (NUMERIC as string with exact scale, mapping_version from mapping_version_id, ISO
timestamps) plus the store/sku filter translation. The DB-backed behaviour (isolation, ordering,
the bound, the store filter) is the integration suite's job.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from dis_core.errors import TenantScopeError
from dis_core.ids import new_uuid7
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.handlers.canonical import _POSITIONS_LIMIT, _iso, _num, _parse_store_id, _to_row
from dis_ui_server.repos.canonical import _LIST_COLUMNS, _build_statement, _tenant_term
from dis_ui_server.schemas.canonical import StoreSkuPositionRow

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees
STORE_A = "0190ac0e-1a01-7001-8a01-0000000000bb"


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _fake_row(**overrides: Any) -> Any:
    """A stand-in for a SQLAlchemy Row over the projection + store_name (attribute access).

    Carries EVERY served column (Slice 52a: 43 canonical columns + store_name) so ``_to_row`` reads
    exactly what the SELECT projects — a missing attribute here is the same drift a prod row would hit.
    """
    base: dict[str, Any] = {
        "id": UUID("0190ac0e-1a01-7001-8a01-000000000001"),
        "store_id": UUID(STORE_A),
        "store_name": "Buc-ee's #101 New Braunfels",
        "sku_id": "BS-SHM-GNG-250",
        "sku_variant": "250ML",
        "sku_lot_batch": "LOT-2026-06",
        "barcode": "8901234567890",
        "product_name": "Ginger Shampoo 250ml",
        "product_description": "Herbal ginger shampoo",
        "product_category": "Personal Care",
        "product_sub_category": "Hair Care",
        "product_department": "HBA",
        "supplier_id": "SUP-014",
        "packaging_type": "Bottle",
        "sku_size": Decimal("250.000"),
        "unit_of_measure": "ml",
        "current_retail_price": Decimal("1299.0000"),
        "unit_cost": Decimal("812.5000"),
        "promo_price": Decimal("999.0000"),
        "promo_identifier": "DIWALI25",
        "yesterday_retail_price": Decimal("1349.0000"),
        "tax_treatment": "INCLUSIVE",
        "stock_qty": Decimal("42.000"),
        "lead_time_days": 5,
        "expiry_date": date(2027, 1, 31),
        "receipt_date": date(2026, 6, 1),
        "expiry_source": "LABEL",
        "expiry_confidence": Decimal("0.95"),
        "regulatory_flag": True,
        "regulatory_type": "DRUG",
        "currency": "INR",
        "reorder_point": Decimal("10.000"),
        "sku_status": "ACTIVE",
        "velocity_7day": Decimal("3.5000"),
        "stock_age_days": 12,
        "unit_cost_trend_30day": Decimal("5.0000"),
        "attribute_staleness_map": {"current_retail_price": "2026-06-09T09:14:41Z"},
        "current_retail_price_changed_at": datetime(2026, 6, 9, 9, 14, 41, tzinfo=UTC),
        "product_name_changed_at": datetime(2026, 5, 1, 8, 0, 0, tzinfo=UTC),
        "last_source_event_at": datetime(2026, 6, 9, 9, 14, 22, tzinfo=UTC),
        "mapping_version_id": 7,
        "trace_id": UUID("0190ac0e-1a01-7001-8a01-0000000000aa"),
        "dis_channel": "csv_upload",
        "last_updated_at": datetime(2026, 6, 9, 9, 14, 41, tzinfo=UTC),
    }
    base.update(overrides)
    return SimpleNamespace(**base)


# -- PURE --------------------------------------------------------------------------


def test_iso_renders_utc_as_z() -> None:
    assert _iso(datetime(2026, 6, 3, 9, 8, 0, tzinfo=UTC)) == "2026-06-03T09:08:00Z"


def test_num_preserves_scale_and_handles_null() -> None:
    # Money-safe: exact NUMERIC scale preserved as a string, not a lossy float.
    assert _num(Decimal("1299.0000")) == "1299.0000"
    assert _num(Decimal("42.000")) == "42.000"
    assert _num(None) is None


def test_parse_store_id_valid() -> None:
    assert str(_parse_store_id(STORE_A)) == STORE_A


@pytest.mark.parametrize("bad", ["not-a-uuid", "", "AMB01"])
def test_parse_store_id_rejects_malformed(bad: str) -> None:
    from dis_core.errors import ResourceNotFoundError

    with pytest.raises(ResourceNotFoundError):
        _parse_store_id(bad)


def test_tenant_term_conditional_on_platform() -> None:
    pinned = _tenant_term(ReadScope(is_platform=False, tenant_id=new_uuid7()))
    assert any("tenant_id" in str(term) for term in pinned), "pinned (TENANT) scope lost its tenant predicate"
    platform = _tenant_term(ReadScope(is_platform=True, tenant_id=None))
    assert not any("tenant_id" in str(term) for term in platform), "PLATFORM see-all still pins a tenant"


def test_tenant_term_refuses_a_pinned_scope_without_a_tenant() -> None:
    with pytest.raises(TenantScopeError):
        _tenant_term(ReadScope(is_platform=False, tenant_id=None))


def test_to_row_maps_canonical_row_to_wire() -> None:
    wire = _to_row(_fake_row())
    assert wire.sku_id == "BS-SHM-GNG-250"
    assert wire.product_name == "Ginger Shampoo 250ml"
    assert wire.current_retail_price == "1299.0000"  # NUMERIC as string, exact scale
    assert wire.stock_qty == "42.000"
    assert wire.currency == "INR"
    assert wire.mapping_version == 7  # from mapping_version_id
    assert wire.last_source_event_at == "2026-06-09T09:14:22Z"  # Observed at
    assert wire.last_updated_at == "2026-06-09T09:14:41Z"  # Written at
    dumped = wire.model_dump()
    assert "mapping_version_id" not in dumped  # renamed to mapping_version
    assert "tenant_id" not in dumped  # scope, never on the wire
    assert "ingest_metadata" not in dumped  # operator-excluded (Slice 52a)


def test_to_row_null_stock_and_event_at() -> None:
    wire = _to_row(_fake_row(stock_qty=None, last_source_event_at=None))
    assert wire.stock_qty is None
    assert wire.last_source_event_at is None


def test_to_row_renders_the_new_columns() -> None:
    wire = _to_row(_fake_row())
    # store_name from the join.
    assert wire.store_name == "Buc-ee's #101 New Braunfels"
    # NUMERIC columns -> money-safe strings with exact scale.
    assert wire.sku_size == "250.000"
    assert wire.unit_cost == "812.5000"
    assert wire.promo_price == "999.0000"
    assert wire.yesterday_retail_price == "1349.0000"
    assert wire.expiry_confidence == "0.95"
    assert wire.reorder_point == "10.000"
    assert wire.velocity_7day == "3.5000"
    assert wire.unit_cost_trend_30day == "5.0000"
    # DATE -> ISO date (no time); TIMESTAMPTZ -> ISO Z.
    assert wire.expiry_date == "2027-01-31"
    assert wire.receipt_date == "2026-06-01"
    assert wire.current_retail_price_changed_at == "2026-06-09T09:14:41Z"
    assert wire.product_name_changed_at == "2026-05-01T08:00:00Z"
    # enum labels pass through as text; smallint -> int; boolean -> bool.
    assert wire.tax_treatment == "INCLUSIVE"
    assert wire.expiry_source == "LABEL"
    assert wire.lead_time_days == 5
    assert wire.stock_age_days == 12
    assert wire.regulatory_flag is True
    assert wire.dis_channel == "csv_upload"
    # jsonb passes through as an object.
    assert wire.attribute_staleness_map == {"current_retail_price": "2026-06-09T09:14:41Z"}


def test_to_row_store_name_null_when_unmirrored() -> None:
    # The FK fk_sscp_store makes a real canonical row's store always mirrored, so this null branch
    # is defensive only — but the mapper/schema must still carry it (store_name: str | None).
    assert _to_row(_fake_row(store_name=None)).store_name is None


def test_to_row_nullable_new_columns_pass_none() -> None:
    wire = _to_row(_fake_row(sku_size=None, expiry_date=None, attribute_staleness_map=None, unit_cost=None))
    assert wire.sku_size is None
    assert wire.expiry_date is None
    assert wire.attribute_staleness_map is None
    assert wire.unit_cost is None


def test_wire_field_set_is_lockstep_with_projection() -> None:
    # The three hand-declaration sites must agree: the SELECT projection (_LIST_COLUMNS) minus the
    # mapping_version_id->mapping_version alias, plus store_name, equals the schema field set. A
    # column added to one site but not the others fails HERE, never silently in prod.
    expected = (set(_LIST_COLUMNS) - {"mapping_version_id"}) | {"mapping_version", "store_name"}
    assert set(StoreSkuPositionRow.model_fields) == expected
    # tenant_id (scope) and ingest_metadata (operator-excluded) are neither projected nor served.
    assert "tenant_id" not in StoreSkuPositionRow.model_fields
    assert "ingest_metadata" not in StoreSkuPositionRow.model_fields
    assert "tenant_id" not in _LIST_COLUMNS
    assert "ingest_metadata" not in _LIST_COLUMNS


def test_store_join_carries_mandatory_tenant_predicate() -> None:
    # Criterion 6 (structural half): identity_mirror.stores is RLS-OFF (D41), so the store-side
    # tenant predicate in the JOIN ON clause is the ONLY tenant isolation on that table and has no
    # behavioural signature (store_id is globally unique + base rows are RLS-forced). This test
    # FAILS if that predicate is ever deleted from the join.
    stmt = _build_statement(
        ReadScope(is_platform=False, tenant_id=UUID(TENANT_A)), limit=50, store_id=None, sku=None
    )
    compiled = str(stmt.compile())  # default compiler renders schema-qualified table.column = table.column
    assert "LEFT OUTER JOIN identity_mirror.stores" in compiled
    assert "identity_mirror.stores.tenant_id = canonical.store_sku_current_position.tenant_id" in compiled, (
        "the mandatory store-side tenant predicate is missing from the join (D41 leak surface)"
    )
    assert "identity_mirror.stores.store_id = canonical.store_sku_current_position.store_id" in compiled


# -- WIRE --------------------------------------------------------------------------


def test_list_requires_a_token(client: TestClient) -> None:
    response = client.get("/api/v1/canonical/store-sku-positions")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "auth_token"


def test_list_denies_platform_without_ops(client: TestClient, mint_token: Callable[..., str]) -> None:
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:read",))
    response = client.get("/api/v1/canonical/store-sku-positions", headers=_bearer(token))
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "ops_role_required"


def test_list_malformed_store_is_404_before_any_db_call(
    client: TestClient, mint_token: Callable[..., str]
) -> None:
    # The DB is unreachable in unit; a 404 here proves the parse rejects BEFORE the read.
    response = client.get(
        "/api/v1/canonical/store-sku-positions?store=AMB01", headers=_bearer(mint_token(tenant_id=TENANT_A))
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "resource_not_found"


def test_list_maps_repo_rows_to_wire(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    async def _fake_list(*_args: Any, **_kwargs: Any) -> list[Any]:
        return [_fake_row()]

    monkeypatch.setattr("dis_ui_server.handlers.canonical.list_positions", _fake_list)
    resp = client.get(
        "/api/v1/canonical/store-sku-positions", headers=_bearer(mint_token(tenant_id=TENANT_A))
    )
    assert resp.status_code == 200
    item = resp.json()["items"][0]
    assert item["sku_id"] == "BS-SHM-GNG-250"
    assert item["current_retail_price"] == "1299.0000"
    assert item["stock_qty"] == "42.000"
    assert item["mapping_version"] == 7
    assert item["currency"] == "INR"


def test_filters_translate(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _capture(*_args: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr("dis_ui_server.handlers.canonical.list_positions", _capture)
    resp = client.get(
        f"/api/v1/canonical/store-sku-positions?store={STORE_A}&sku=BS-SHM",
        headers=_bearer(mint_token(tenant_id=TENANT_A)),
    )
    assert resp.status_code == 200
    assert captured["store_id"] == UUID(STORE_A)  # parsed to UUID
    assert captured["sku"] == "BS-SHM"  # passthrough (the repo escapes for ILIKE)
    assert captured["limit"] == _POSITIONS_LIMIT


def test_no_filters_pass_none(
    client: TestClient, mint_token: Callable[..., str], monkeypatch: pytest.MonkeyPatch
) -> None:
    captured: dict[str, Any] = {}

    async def _capture(*_args: Any, **kwargs: Any) -> list[Any]:
        captured.update(kwargs)
        return []

    monkeypatch.setattr("dis_ui_server.handlers.canonical.list_positions", _capture)
    resp = client.get(
        "/api/v1/canonical/store-sku-positions", headers=_bearer(mint_token(tenant_id=TENANT_A))
    )
    assert resp.status_code == 200
    assert captured["store_id"] is None
    assert captured["sku"] is None
    assert captured["limit"] == _POSITIONS_LIMIT
