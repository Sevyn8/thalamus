"""``GET /canonical/store-sku-positions`` — the Canonical Data Explorer list (read-only).

Tenant from the verified token ONLY (no path/query/header tenant input). The read goes through
``repos/canonical.py``, which scopes every statement under ``read_session`` (canonical's two-GUC
RLS is the database backstop) plus an explicit tenant predicate. Wire<->DB translation lives HERE
(Decimal->str money-safe rendering, ISO timestamp + date rendering, enum-as-text, store_id parse);
the repo speaks DB vocabulary only.

The served fields are the FULL live column set of store_sku_current_position
EXCEPT tenant_id (scope) and ingest_metadata (operator-excluded), plus a human-readable store_name
LEFT-joined from identity_mirror.stores (null when unmirrored). mapping_version is the sole
version key (from mapping_version_id).

READ-ONLY (canonical is in the service read-set; the consumer/daily-compute are its sole
writers). LIST-ONLY, BOUNDED to the newest ``_POSITIONS_LIMIT`` positions (the mockup's "sample
rows"). The per-value source->transform lineage (the mockup's row drawer) is still NOT served — it
is not stored on the canonical row; mapping_version / trace_id / observed+written timestamps remain
the servable lineage anchors.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.errors import ResourceNotFoundError
from dis_ui_server.auth.scope import ReadScope, require_read_scope
from dis_ui_server.repos.canonical import list_positions
from dis_ui_server.schemas.canonical import StoreSkuPositionListResponse, StoreSkuPositionRow

router = APIRouter()

# The bounded newest-N sample (no pagination this slice; canonical is high-volume).
_POSITIONS_LIMIT = 50


def _iso(value: datetime) -> str:
    """ISO-8601 with the UTC offset rendered as ``Z`` (the wire convention)."""
    return value.isoformat().replace("+00:00", "Z")


def _num(value: Decimal | None) -> str | None:
    """NUMERIC -> string (money-safe; the exact scale is preserved for the UI to format)."""
    return None if value is None else str(value)


def _date(value: date | None) -> str | None:
    """DATE -> ISO-8601 date string (no time component; null passes through)."""
    return None if value is None else value.isoformat()


def _parse_store_id(store_id: str) -> UUID:
    """Parse the ``store`` filter as a UUID; a malformed value is a clean 404.

    404 (not 422) keeps the no-existence-oracle posture: a malformed store handle and an unknown
    store both surface as "no such store for you", never an oracle on store shape.
    """
    try:
        return UUID(store_id)
    except ValueError as exc:
        raise ResourceNotFoundError(
            f"store id {store_id!r} is not a valid store identifier",
            resource="store",
            identifier=store_id,
        ) from exc


def _to_row(row: Row[Any]) -> StoreSkuPositionRow:
    return StoreSkuPositionRow(
        id=str(row.id),
        store_id=str(row.store_id),
        store_name=row.store_name,  # from the identity_mirror.stores join; null when unmirrored
        sku_id=row.sku_id,
        sku_variant=row.sku_variant,
        sku_lot_batch=row.sku_lot_batch,
        barcode=row.barcode,
        product_name=row.product_name,
        product_description=row.product_description,
        product_category=row.product_category,
        product_sub_category=row.product_sub_category,
        product_department=row.product_department,
        supplier_id=row.supplier_id,
        packaging_type=row.packaging_type,
        sku_size=_num(row.sku_size),
        unit_of_measure=row.unit_of_measure,
        current_retail_price=_num(row.current_retail_price) or "0",  # NOT NULL in DB
        unit_cost=_num(row.unit_cost),
        promo_price=_num(row.promo_price),
        promo_identifier=row.promo_identifier,
        yesterday_retail_price=_num(row.yesterday_retail_price),
        tax_treatment=row.tax_treatment,  # enum label (NOT NULL)
        stock_qty=_num(row.stock_qty),
        lead_time_days=row.lead_time_days,
        expiry_date=_date(row.expiry_date),
        receipt_date=_date(row.receipt_date),
        expiry_source=row.expiry_source,  # enum label
        expiry_confidence=_num(row.expiry_confidence),
        regulatory_flag=row.regulatory_flag,
        regulatory_type=row.regulatory_type,
        currency=row.currency,
        reorder_point=_num(row.reorder_point),
        sku_status=row.sku_status,
        velocity_7day=_num(row.velocity_7day),
        stock_age_days=row.stock_age_days,
        unit_cost_trend_30day=_num(row.unit_cost_trend_30day),
        attribute_staleness_map=row.attribute_staleness_map,  # jsonb pass-through
        current_retail_price_changed_at=(
            _iso(row.current_retail_price_changed_at)
            if row.current_retail_price_changed_at is not None
            else None
        ),
        product_name_changed_at=(
            _iso(row.product_name_changed_at) if row.product_name_changed_at is not None else None
        ),
        last_source_event_at=(
            _iso(row.last_source_event_at) if row.last_source_event_at is not None else None
        ),
        mapping_version=row.mapping_version_id,  # sole version key; raw id not exposed
        trace_id=str(row.trace_id),
        dis_channel=row.dis_channel,
        last_updated_at=_iso(row.last_updated_at),
    )


@router.get("/canonical/store-sku-positions")
async def list_store_sku_positions(
    request: Request,
    scope: Annotated[ReadScope, Depends(require_read_scope)],
    store: Annotated[str | None, Query()] = None,
    sku: Annotated[str | None, Query()] = None,
) -> StoreSkuPositionListResponse:
    """A bounded newest-first sample of canonical positions. TENANT sees its own; PLATFORM
    (user_type=PLATFORM + dis:ops) sees cross-tenant."""
    engine: AsyncEngine = request.app.state.engine
    parsed_store = _parse_store_id(store) if store is not None else None
    positions = await list_positions(engine, scope, limit=_POSITIONS_LIMIT, store_id=parsed_store, sku=sku)
    return StoreSkuPositionListResponse(items=[_to_row(p) for p in positions])
