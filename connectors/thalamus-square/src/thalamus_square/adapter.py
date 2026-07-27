"""SquareAdapter: implements the thalamus_connector_sdk ConnectorAdapter against Square.

- ``authenticate`` resolves the tenant's token and validates it by listing locations.
- ``discover`` returns the locations and a native-schema sketch (seeds a template proposal).
- ``extract`` maps CATALOG+INVENTORY to snapshot rows and ORDERS to sale-event rows,
  cursor incremental.
- ``preflight`` reuses the SDK's structural ``run_preflight``.

Store to Square-location association is a provisioning concern; v1 (sandbox) uses the
locations the token can see. The trigger's ``store_id`` scopes the bronze row and the
downstream write, so the CSV rows carry no store column.
"""

from __future__ import annotations

from thalamus_connector_sdk import (
    DROPPED_SAMPLE_MAX,
    AuthContext,
    ConnectorExtractError,
    ConnectorReasonCode,
    Cursor,
    Discovery,
    Domain,
    ExtractResult,
    ExtractRow,
    PreflightResult,
    run_preflight,
)
from thalamus_connector_sdk.trigger import ConnectorTrigger
from thalamus_square.auth import TokenStore
from thalamus_square.mapping import (
    SALES_HEADER,
    SNAPSHOT_HEADER,
    catalog_inventory_to_rows,
    inventory_to_rows,
    orders_to_rows,
)
from thalamus_square.puller import SquareApi

_LOCATION_IDS = "location_ids"


class SquareAdapter:
    """The Square connector adapter (satisfies ConnectorAdapter structurally)."""

    def __init__(self, *, api: SquareApi, token_store: TokenStore) -> None:
        self._api = api
        self._token_store = token_store

    def authenticate(self, trigger: ConnectorTrigger) -> AuthContext:
        token = self._token_store.get_token(trigger.tenant_id, trigger.source_id)
        locations = self._api.list_locations(token)  # validates the token; raises on 401/403
        location_ids = [str(loc.get("id")) for loc in locations if loc.get("id")]
        store_by_code = {str(loc.get("id")): str(loc.get("name") or "") for loc in locations if loc.get("id")}
        return AuthContext(token=token, store_by_code=store_by_code, extra={_LOCATION_IDS: location_ids})

    def discover(self, auth: AuthContext) -> Discovery:
        locations = tuple(auth.store_by_code.keys())
        native_schema = {
            "catalog": ["ITEM.item_data.name", "ITEM_VARIATION.item_variation_data.price_money"],
            "inventory": ["counts.quantity"],
            "orders": ["order.line_items.base_price_money"],
        }
        return Discovery(locations=locations, native_schema=native_schema)

    def extract(self, auth: AuthContext, domain: Domain, cursor: Cursor | None) -> ExtractResult:
        location_ids = list(auth.extra.get(_LOCATION_IDS) or [])
        if domain is Domain.CATALOG:
            return self._extract_catalog(auth, cursor, location_ids, full=True)
        if domain is Domain.INVENTORY:
            return self._extract_catalog(auth, cursor, location_ids, full=False)
        if domain is Domain.ORDERS:
            return self._extract_orders(auth, cursor, location_ids)
        raise ConnectorExtractError(  # pragma: no cover - Domain is a closed enum
            f"unsupported domain {domain!r}", reason=ConnectorReasonCode.SCHEMA_UNRECOGNIZED
        )

    def preflight(self, extract: ExtractResult) -> PreflightResult:
        return run_preflight(extract)

    # -- domain extracts --------------------------------------------------------

    def _extract_catalog(
        self, auth: AuthContext, cursor: Cursor | None, location_ids: list[str], *, full: bool
    ) -> ExtractResult:
        page = self._api.list_catalog(auth.token, cursor)
        variation_ids = [
            str(variation.get("id"))
            for item in page.items
            for variation in (item.get("item_data") or {}).get("variations") or []
            if variation.get("id")
        ]
        inventory = self._api.batch_inventory(
            auth.token, catalog_object_ids=variation_ids, location_ids=location_ids
        )
        dropped: list[str] = []
        if full:
            rows, dropped = catalog_inventory_to_rows(
                page.items, categories=page.categories, inventory_by_variation=inventory
            )
            header = SNAPSHOT_HEADER
        else:
            rows = inventory_to_rows(inventory)
            header = ("sku_id", "stock_qty")
        return ExtractResult(
            domain=Domain.CATALOG if full else Domain.INVENTORY,
            header=header,
            rows=tuple(rows),
            next_cursor=page.next_cursor,
            dropped_count=len(dropped),
            dropped_sample=tuple(dropped[:DROPPED_SAMPLE_MAX]),
            rate_limit_state=self._api.rate_limit_state(),
        )

    def _extract_orders(
        self, auth: AuthContext, cursor: Cursor | None, location_ids: list[str]
    ) -> ExtractResult:
        page = self._api.search_orders(auth.token, location_ids=location_ids, cursor=cursor)
        rows: list[ExtractRow] = orders_to_rows(page.orders)
        return ExtractResult(
            domain=Domain.ORDERS,
            header=SALES_HEADER,
            rows=tuple(rows),
            next_cursor=page.next_cursor,
            rate_limit_state=self._api.rate_limit_state(),
        )
