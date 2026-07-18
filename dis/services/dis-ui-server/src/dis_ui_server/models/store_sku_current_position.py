"""``canonical.store_sku_current_position`` — the hot per-(tenant,store,sku) position (READ-ONLY).

A faithful read mirror of the columns the ``GET /canonical/store-sku-positions`` list serves.
dis-ui-server reads canonical read-only (already in the service read-set — CLAUDE.md "Reads from:
Cloud SQL read replica (canonical)"; today only the dashboard reads it, via count(*)). The
streaming consumer / daily-compute remain canonical's SOLE writers (root CLAUDE.md); this model
is typed read metadata only — the canonical repo builds SELECT-only statements.

RLS is the standard two-GUC policy (D91): ``tenant_isolation`` = ``USING (tenant_id =
app.tenant_id OR app.user_type='PLATFORM')`` + ``WITH CHECK`` tenant-pin — identical READ
behaviour to ``quarantine.*`` / bronze. tenant_id is NOT NULL (no system rows). The per-tenant
scope rides ``read_session``; the explicit ``WHERE tenant_id`` predicate in ``repos/canonical.py``
is defense-in-depth.

Slice 52a widens the served set to the FULL live column set of the table EXCEPT ``tenant_id``
(scope, never on the wire) and ``ingest_metadata`` (operator-excluded, drawer-noise) — 43 canonical
columns, plus ``store_name`` attached by the repo's ``identity_mirror.stores`` join. So the mirror is
now near-complete by design; every served column is a mapped attribute here because the repo's
``_LIST_COLUMNS`` resolves each via ``getattr`` on this model. ``ingest_metadata`` is intentionally
NOT mapped (not served). Enum columns (``tax_treatment``, ``expiry_source``) map as ``String`` — for
a read-only SELECT the DB enum value comes back as its text label. The per-value source->transform
lineage (the mockup's drawer) is still NOT stored here — it needs a mapping_rules join + the source
payload, out of scope for this read.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from sqlalchemy import BigInteger, Boolean, Date, DateTime, Numeric, SmallInteger, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from dis_ui_server.db import Base


class StoreSkuCurrentPosition(Base):
    """One canonical position (faithful read mirror of the served columns)."""

    __tablename__ = "store_sku_current_position"
    __table_args__ = {"schema": "canonical"}

    # Columns in live-schema ordinal order. tenant_id is mapped (join predicate + RLS) but NEVER
    # served; ingest_metadata (ordinal 45) is intentionally absent (operator-excluded, not served).
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(Uuid)  # NOT NULL (no system rows); scope-only, off the wire
    store_id: Mapped[UUID] = mapped_column(Uuid)  # NOT NULL
    sku_id: Mapped[str] = mapped_column(String(128))
    sku_variant: Mapped[str | None] = mapped_column(String(128))
    sku_lot_batch: Mapped[str | None] = mapped_column(String(128))
    barcode: Mapped[str | None] = mapped_column(String(128))
    product_name: Mapped[str] = mapped_column(String(128))  # NOT NULL; the SKU display name
    product_description: Mapped[str | None] = mapped_column(String(128))
    product_category: Mapped[str | None] = mapped_column(String(128))
    product_sub_category: Mapped[str | None] = mapped_column(String(128))
    product_department: Mapped[str | None] = mapped_column(String(128))
    supplier_id: Mapped[str | None] = mapped_column(String(128))
    packaging_type: Mapped[str | None] = mapped_column(String(128))
    sku_size: Mapped[Decimal | None] = mapped_column(Numeric(8, 3))
    unit_of_measure: Mapped[str | None] = mapped_column(String(64))
    current_retail_price: Mapped[Decimal] = mapped_column(Numeric(12, 4))  # Unit price (NOT NULL)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    promo_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    promo_identifier: Mapped[str | None] = mapped_column(String(128))
    yesterday_retail_price: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    tax_treatment: Mapped[str] = mapped_column(String)  # tax_treatment_enum (NOT NULL); read as text
    stock_qty: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))  # On hand (nullable)
    lead_time_days: Mapped[int | None] = mapped_column(SmallInteger)
    expiry_date: Mapped[date | None] = mapped_column(Date)
    receipt_date: Mapped[date | None] = mapped_column(Date)
    expiry_source: Mapped[str | None] = mapped_column(String)  # canonical.expiry_source_enum; read as text
    expiry_confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2))
    regulatory_flag: Mapped[bool | None] = mapped_column(Boolean)
    regulatory_type: Mapped[str | None] = mapped_column(String(128))
    currency: Mapped[str] = mapped_column(String(3))  # CHAR(3) NOT NULL — for money rendering
    reorder_point: Mapped[Decimal | None] = mapped_column(Numeric(14, 3))
    sku_status: Mapped[str | None] = mapped_column(String(32))
    velocity_7day: Mapped[Decimal | None] = mapped_column(Numeric(10, 4))
    stock_age_days: Mapped[int | None] = mapped_column(SmallInteger)
    unit_cost_trend_30day: Mapped[Decimal | None] = mapped_column(Numeric(12, 4))
    attribute_staleness_map: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    current_retail_price_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    product_name_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_source_event_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # Observed at
    mapping_version_id: Mapped[int] = mapped_column(BigInteger)  # NOT NULL; mapping_version source
    trace_id: Mapped[UUID] = mapped_column(Uuid)  # NOT NULL — lineage anchor
    dis_channel: Mapped[str] = mapped_column(String(32))  # NOT NULL
    last_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # Written at (Updated)
