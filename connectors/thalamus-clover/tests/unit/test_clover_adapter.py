"""CloverAdapter over a fake Clover API (no network).

Proves the adapter satisfies the ConnectorAdapter contract: authenticate resolves the
SESSION (token + merchant) and caches the currency, extract joins the three collections
into snapshot rows, and preflight reuses the SDK verdict.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest

from thalamus_clover.adapter import CloverAdapter
from thalamus_clover.fakes import FakeCloverApi, FakeSessionStore
from thalamus_clover.mapping import SNAPSHOT_HEADER
from thalamus_clover.puller import ItemPage
from thalamus_connector_sdk import (
    RATE_LIMIT_THROTTLED,
    AuthContext,
    ConnectorExtractError,
    ConnectorReasonCode,
    Domain,
    ExtractResult,
    ExtractRow,
)
from thalamus_connector_sdk.trigger import ConnectorTrigger

_TENANT = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")
_STORE = UUID("019f9d71-b356-7caf-8c56-04e5ba6670d0")
_TRACE = UUID("019e8d88-4e76-7911-bb77-d8fcba1808a6")
_TEMPLATE = UUID("019e93f0-57ca-7470-9899-ba6532ff1600")


def _trigger(domain: Domain = Domain.CATALOG) -> ConnectorTrigger:
    return ConnectorTrigger(
        schema_version=1,
        trace_id=_TRACE,
        connector_run_id="run_clover_0001",
        tenant_id=_TENANT,
        store_id=_STORE,
        source_id="clover_pos_v1",
        template_id=_TEMPLATE,
        domains=[domain],
        cursor=None,
    )


def _adapter(api: Any = None) -> CloverAdapter:
    return CloverAdapter(api=api or FakeCloverApi(), token_store=FakeSessionStore())


def _authed(adapter: CloverAdapter) -> AuthContext:
    return adapter.authenticate(_trigger())


# -- authenticate ------------------------------------------------------------------------


def test_authenticate_carries_the_merchant_and_currency() -> None:
    # Every Clover path is merchant-scoped, and currency is not on the item, so both must
    # survive authenticate or every later call is impossible.
    auth = _authed(_adapter())
    assert auth.token == "fake-sandbox-token"
    assert auth.extra["merchant_id"] == "0RKKDBMKPAH71"
    assert auth.extra["currency"] == "USD"


def test_authenticate_fetches_the_merchant_exactly_once() -> None:
    # Currency is cached for the run's lifetime, not re-fetched per page.
    class _Counting(FakeCloverApi):
        calls = 0

        def get_merchant(self, token: str, merchant_id: str) -> dict[str, Any]:
            type(self).calls += 1
            return super().get_merchant(token, merchant_id)

    api = _Counting()
    adapter = _adapter(api)
    auth = _authed(adapter)
    adapter.extract(auth, Domain.CATALOG, None)
    adapter.extract(auth, Domain.CATALOG, None)
    assert _Counting.calls == 1


# -- extract -----------------------------------------------------------------------------


def test_extract_catalog_produces_snapshot_rows() -> None:
    adapter = _adapter()
    result = adapter.extract(_authed(adapter), Domain.CATALOG, None)
    assert result.domain is Domain.CATALOG
    assert result.header == SNAPSHOT_HEADER
    assert isinstance(result.rows[0], ExtractRow)
    by_id = {r.values["sku_id"]: r.values for r in result.rows}
    # The PER_UNIT item is dropped and counted; the other four survive.
    assert result.dropped_count == 1
    assert "ITEM_LOOSETEA" in result.dropped_sample
    assert set(by_id) == {"ITEM_MANGO", "STAT-PENCIL-01", "ITEM_NOODLES", "ITEM_GIFTSET"}


def test_a_negative_stock_suppresses_the_field_but_keeps_the_row() -> None:
    class _Oversold(FakeCloverApi):
        def list_item_stocks(self, token: str, merchant_id: str) -> dict[str, str]:
            return {"ITEM_MANGO": "-2", "STAT-PENCIL-01": "42"}

    adapter = _adapter(_Oversold())
    result = adapter.extract(_authed(adapter), Domain.CATALOG, None)
    rows = {r.values["sku_id"]: r.values for r in result.rows}
    assert "stock_qty" not in rows["ITEM_MANGO"]  # withheld, not clamped
    # The row survives and the ROW-drop counter is untouched by a FIELD suppression.
    assert "ITEM_MANGO" in rows
    assert result.dropped_count == 1  # still just the PER_UNIT item
    assert "ITEM_MANGO" not in result.dropped_sample


def test_extract_threads_both_stock_branches_end_to_end() -> None:
    adapter = _adapter()
    rows = {
        r.values["sku_id"]: r.values for r in adapter.extract(_authed(adapter), Domain.CATALOG, None).rows
    }
    assert rows["ITEM_MANGO"]["stock_qty"] == "0"  # tracked, genuinely zero
    assert rows["STAT-PENCIL-01"]["stock_qty"] == "42"  # tracked
    assert "stock_qty" not in rows["ITEM_NOODLES"]  # untracked -> omitted, never 0
    assert "stock_qty" not in rows["ITEM_GIFTSET"]


def test_extract_applies_the_deterministic_category_pick() -> None:
    adapter = _adapter()
    rows = {
        r.values["sku_id"]: r.values for r in adapter.extract(_authed(adapter), Domain.CATALOG, None).rows
    }
    # Gift Set is in both categories; Stationary (sortOrder 1) wins.
    assert rows["ITEM_GIFTSET"]["product_category"] == "Stationary"


def test_extract_carries_the_rate_limit_posture() -> None:
    class _Throttled(FakeCloverApi):
        def rate_limit_state(self) -> str | None:
            return RATE_LIMIT_THROTTLED

    adapter = _adapter(_Throttled())
    assert adapter.extract(_authed(adapter), Domain.CATALOG, None).rate_limit_state == RATE_LIMIT_THROTTLED


def test_extract_passes_the_cursor_through_and_returns_the_next_one() -> None:
    class _Paged(FakeCloverApi):
        seen: list[str | None] = []

        def list_items(self, token: str, merchant_id: str, cursor: str | None) -> ItemPage:
            type(self).seen.append(cursor)
            return ItemPage(items=[], next_cursor="1000")

    adapter = _adapter(_Paged())
    result = adapter.extract(_authed(adapter), Domain.CATALOG, "500")
    assert _Paged.seen == ["500"]
    assert result.next_cursor == "1000"


# -- unsupported domains --------------------------------------------------------------------


@pytest.mark.parametrize("domain", [Domain.INVENTORY, Domain.ORDERS])
def test_unsupported_domains_raise_rather_than_return_nothing(domain: Domain) -> None:
    # ORDERS needs scopes this app has not been granted; silently returning zero rows would
    # look like a merchant with no sales.
    adapter = _adapter()
    auth = _authed(adapter)
    with pytest.raises(ConnectorExtractError) as exc:
        adapter.extract(auth, domain, None)
    assert exc.value.reason is ConnectorReasonCode.SCHEMA_UNRECOGNIZED


# -- preflight ---------------------------------------------------------------------------------


def test_preflight_flags_an_empty_extract() -> None:
    empty = ExtractResult(domain=Domain.CATALOG, header=SNAPSHOT_HEADER, rows=(), next_cursor=None)
    assert not _adapter().preflight(empty).ok


def test_preflight_passes_a_real_extract() -> None:
    adapter = _adapter()
    result = adapter.extract(_authed(adapter), Domain.CATALOG, None)
    assert adapter.preflight(result).ok
