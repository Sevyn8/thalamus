"""CloverAdapter: implements the thalamus_connector_sdk ConnectorAdapter against Clover.

- ``authenticate`` resolves the tenant's SESSION (token + merchant id) and validates it by
  fetching the merchant, caching ``defaultCurrency`` for the run.
- ``discover`` returns the merchant and a native-schema sketch (seeds a template proposal).
- ``extract`` maps CATALOG to snapshot rows, offset incremental.
- ``preflight`` reuses the SDK's structural ``run_preflight``.

WHY A SESSION AND NOT A TOKEN. Every Clover REST path is ``/v3/merchants/{mId}/...``, so
the merchant id is needed on every call. ``CloverTokenStore.get_session`` returns both in
one vault read. The Square adapter takes only a token because Square's API is not
merchant-scoped in the path.

CURRENCY IS FETCHED ONCE. It lives on merchant properties, not on the item, so it is read
during ``authenticate`` and carried on ``AuthContext.extra`` for the run's lifetime rather
than re-fetched per page.

Only CATALOG is implemented. INVENTORY has no separate meaning here (stock rides the
snapshot), and ORDERS needs scopes this app has not been granted - both raise the SDK's
structural error rather than silently returning nothing.
"""

from __future__ import annotations

from typing import Protocol
from uuid import UUID

from dis_core.logging import get_logger
from thalamus_clover.config import SERVICE_NAME
from thalamus_clover.mapping import (
    SNAPSHOT_HEADER,
    STOCK_SUPPRESSED_NEGATIVE,
    STOCK_SUPPRESSED_UNPARSEABLE,
    StockSuppressions,
    items_to_rows,
)
from thalamus_clover.puller import CloverApi
from thalamus_clover_oauth import CloverSession
from thalamus_connector_sdk import (
    DROPPED_SAMPLE_MAX,
    AuthContext,
    ConnectorExtractError,
    ConnectorReasonCode,
    Cursor,
    Discovery,
    Domain,
    ExtractResult,
    PreflightResult,
    run_preflight,
)
from thalamus_connector_sdk.trigger import ConnectorTrigger

_log = get_logger(SERVICE_NAME)

# Bound on the suppressed-item sample in the warn log: enough to identify the pattern,
# never the whole catalog.
_SUPPRESSED_SAMPLE_MAX = 20

_MERCHANT_ID = "merchant_id"
_CURRENCY = "currency"

# Where Clover keeps the merchant's currency: merchant.properties.defaultCurrency.
_PROPERTIES = "properties"
_DEFAULT_CURRENCY = "defaultCurrency"


class SessionStore(Protocol):
    """Yields a tenant/source's Clover session (token + merchant), or raises.

    Narrower than ``CloverTokenStore``: the adapter needs ``get_session`` and nothing else,
    so tests inject a two-line fake and production passes the real store unchanged.
    """

    def get_session(self, tenant_id: UUID, source_id: str) -> CloverSession: ...


class CloverAdapter:
    """The Clover connector adapter (satisfies ConnectorAdapter structurally)."""

    def __init__(self, *, api: CloverApi, token_store: SessionStore) -> None:
        self._api = api
        self._token_store = token_store

    def authenticate(self, trigger: ConnectorTrigger) -> AuthContext:
        session = self._token_store.get_session(trigger.tenant_id, trigger.source_id)
        # Validates the token AND yields the currency in one call; raises on 401/403.
        merchant = self._api.get_merchant(session.access_token, session.merchant_id)
        currency = str((merchant.get(_PROPERTIES) or {}).get(_DEFAULT_CURRENCY) or "")
        merchant_name = str(merchant.get("name") or "")
        return AuthContext(
            token=session.access_token,
            store_by_code={session.merchant_id: merchant_name},
            extra={_MERCHANT_ID: session.merchant_id, _CURRENCY: currency},
        )

    def discover(self, auth: AuthContext) -> Discovery:
        native_schema = {
            "items": ["id", "name", "sku", "price", "priceType", "categories.elements[].id"],
            "categories": ["id", "name", "sortOrder"],
            "item_stocks": ["item.id", "quantity"],
            "merchant": ["properties.defaultCurrency"],
        }
        return Discovery(locations=tuple(auth.store_by_code.keys()), native_schema=native_schema)

    def extract(self, auth: AuthContext, domain: Domain, cursor: Cursor | None) -> ExtractResult:
        if domain is Domain.CATALOG:
            return self._extract_catalog(auth, cursor)
        raise ConnectorExtractError(
            f"the Clover connector implements CATALOG only; {domain.value} is not available "
            "(ORDERS needs scopes this app has not been granted)",
            reason=ConnectorReasonCode.SCHEMA_UNRECOGNIZED,
        )

    def preflight(self, extract: ExtractResult) -> PreflightResult:
        return run_preflight(extract)

    # -- domain extracts --------------------------------------------------------

    def _log_suppressions(self, suppressions: StockSuppressions, *, merchant_id: str) -> None:
        """Report withheld stock quantities, the TWO CAUSES SEPARATELY.

        A warn log is the only surfacing channel available without an SDK change:
        ``dropped_count``, the health metadata and the RECEIVED audit ``event_data`` are all
        built by the pipeline from the ROW-drop counter, and a suppressed FIELD must not ride
        that (see mapping.py).

        The two messages are deliberately distinct and carry distinct reason tokens. A
        negative quantity is ordinary merchant behaviour; an unparseable one means Clover's
        wire contract moved. Sharing one line would make the day Clover changes that field's
        type read as a busy day of overselling, and we would notice weeks later as "all our
        stock went null".
        """
        log = _log.bind(stage="extract", merchant_id=merchant_id)
        if suppressions.negative:
            log.warning(
                f"reason={STOCK_SUPPRESSED_NEGATIVE} "
                f"{len(suppressions.negative)} item(s) reported a NEGATIVE stock quantity; "
                "stock_qty withheld as NULL. Clover permits overselling, canonical "
                "ck_sscp_stock_qty_non_negative does not. Expected in production; rows still "
                f"emitted. ids={suppressions.negative[:_SUPPRESSED_SAMPLE_MAX]}"
            )
        if suppressions.unparseable:
            log.warning(
                f"reason={STOCK_SUPPRESSED_UNPARSEABLE} "
                f"{len(suppressions.unparseable)} item(s) reported a stock quantity that is "
                "NOT A NUMBER; stock_qty withheld as NULL. This is a VENDOR SCHEMA BREAK, not "
                "merchant behaviour - Clover's wire contract for that field has changed and "
                f"the mapping needs review. ids={suppressions.unparseable[:_SUPPRESSED_SAMPLE_MAX]}"
            )

    def _extract_catalog(self, auth: AuthContext, cursor: Cursor | None) -> ExtractResult:
        merchant_id = str(auth.extra.get(_MERCHANT_ID) or "")
        currency = str(auth.extra.get(_CURRENCY) or "")
        page = self._api.list_items(auth.token, merchant_id, cursor)
        # Two whole-collection side inputs, both cheap and both self-evidencing (we can
        # count them), unlike an expand whose failure is silent.
        categories = self._api.list_categories(auth.token, merchant_id)
        stock_by_item = self._api.list_item_stocks(auth.token, merchant_id)
        rows, dropped, suppressions = items_to_rows(
            page.items, categories=categories, stock_by_item=stock_by_item, currency=currency
        )
        self._log_suppressions(suppressions, merchant_id=merchant_id)
        return ExtractResult(
            domain=Domain.CATALOG,
            header=SNAPSHOT_HEADER,
            rows=tuple(rows),
            next_cursor=page.next_cursor,
            dropped_count=len(dropped),
            dropped_sample=tuple(dropped[:DROPPED_SAMPLE_MAX]),
            rate_limit_state=self._api.rate_limit_state(),
        )
