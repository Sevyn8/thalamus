"""Wire shapes for the Canonical Data Explorer (GET /canonical/store-sku-positions).

One endpoint consumes this: ``GET /canonical/store-sku-positions`` — a bounded newest-first
sample of the tenant's canonical positions (``canonical.store_sku_current_position``), the
mockup's Stock-position entity: SKU · Store · On hand · Unit price · Mapping · Updated.

Money / quantity fields are NUMERIC in the DB (``current_retail_price NUMERIC(12,4)``,
``stock_qty NUMERIC(14,3)``). They are carried on the wire as STRINGS, not floats: retail money
must not suffer binary-float rounding, and the exact scale is preserved for the UI to format
(₹ grouping, decimals). The handler renders ``Decimal -> str``; the frontend formats. (Existing
schemas only carry ``float`` for approximate ratios like the quarantine rate — a different case.)

The per-value source->transform LINEAGE (the mockup's row drawer) is NOT served here: it is not
stored on the canonical row (it needs a mapping_rules join + the source payload). This is the
list only; the mapping_version / trace_id / observed+written timestamps are the servable lineage
anchors carried per row.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class StoreSkuPositionRow(BaseModel):
    """One canonical position — the FULL live column set of store_sku_current_position EXCEPT
    tenant_id (scope) and ingest_metadata (operator-excluded), plus store_name.

    Additive over the original 11-field shape: every prior key keeps its name, type, and rendered
    value. NUMERIC columns are carried as money-safe strings (exact scale preserved; no binary-float
    rounding); timestamps as ISO-8601 Z; dates as ISO-8601 date; the two enums (tax_treatment,
    expiry_source) as their text label; attribute_staleness_map as a jsonb pass-through object.
    mapping_version stays the SOLE version key (aliased from the mapping_version_id column); the raw
    mapping_version_id is not exposed. Field order mirrors the live-schema ordinal order (store_name
    sits beside store_id). This is one of three lockstep declaration sites (the repo SELECT projection
    and the handler row mapper are the others); a drift is caught by a test, never shipped."""

    id: str
    store_id: str  # Store (the store UUID)
    store_name: str | None  # identity_mirror.stores.name; null when the store is unmirrored
    sku_id: str  # SKU
    sku_variant: str | None
    sku_lot_batch: str | None
    barcode: str | None
    product_name: str  # the SKU display name
    product_description: str | None
    product_category: str | None
    product_sub_category: str | None
    product_department: str | None
    supplier_id: str | None
    packaging_type: str | None
    sku_size: str | None  # NUMERIC as string
    unit_of_measure: str | None
    current_retail_price: str  # Unit price — NUMERIC as string (money-safe)
    unit_cost: str | None  # NUMERIC as string
    promo_price: str | None  # NUMERIC as string
    promo_identifier: str | None
    yesterday_retail_price: str | None  # NUMERIC as string
    tax_treatment: str  # enum label (NOT NULL)
    stock_qty: str | None  # On hand — NUMERIC as string (money-safe), null when unset
    lead_time_days: int | None
    expiry_date: str | None  # ISO-8601 date
    receipt_date: str | None  # ISO-8601 date
    expiry_source: str | None  # enum label
    expiry_confidence: str | None  # NUMERIC as string
    regulatory_flag: bool | None
    regulatory_type: str | None
    currency: str  # ISO currency (for money rendering)
    reorder_point: str | None  # NUMERIC as string
    sku_status: str | None
    velocity_7day: str | None  # NUMERIC as string
    stock_age_days: int | None
    unit_cost_trend_30day: str | None  # NUMERIC as string
    attribute_staleness_map: dict[str, Any] | None  # jsonb pass-through (per-attribute staleness)
    current_retail_price_changed_at: str | None  # ISO-8601 Z
    product_name_changed_at: str | None  # ISO-8601 Z
    last_source_event_at: str | None  # Observed at — ISO-8601 Z, null if never event-written
    mapping_version: int  # from mapping_version_id (sole version key; the raw id is not exposed)
    trace_id: str  # lineage anchor (servable; the full source->transform trace is L1)
    dis_channel: str  # ingress channel (NOT NULL)
    last_updated_at: str  # Written at / Updated — ISO-8601 Z


class StoreSkuPositionListResponse(BaseModel):
    """The list body: a bounded newest-first sample of the tenant's canonical positions."""

    items: list[StoreSkuPositionRow]
