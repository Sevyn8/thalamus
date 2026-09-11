"""``canonical.store_sku_current_position`` reads — the Canonical Explorer data access.

READ-ONLY: canonical is in the service read-set; the streaming consumer /
daily-compute remain its SOLE writers. This module builds SELECT-only statements — never an
INSERT/UPDATE/DELETE.

The table is RLS ON + FORCE with the standard two-GUC ``tenant_isolation`` policy: ``USING
(tenant_id = app.tenant_id OR app.user_type='PLATFORM')`` — identical READ behaviour to
``quarantine.*`` / bronze, so the per-tenant scope is the DATABASE's guarantee, applied by
``read_session``. The explicit ``WHERE tenant_id`` predicate here is defense-in-depth. tenant_id
is NOT NULL — no system/null rows.

Reads execute CORE-STYLE on the ``read_session`` connection; never an
``AsyncSession``, never a ``.commit()``. This module speaks DB vocabulary
only — Decimal->str / ISO rendering lives in the handler. The list is a BOUNDED newest-first
sample by ``last_updated_at`` (the mockup's "sample rows"; canonical is high-volume). The
``store_id`` filter rides ``ix_sscp_tenant_store``. ``scope`` MUST come from the verified token
(``require_read_scope``); this module trusts its caller on that.

A human-readable ``store_name`` is LEFT-joined from ``identity_mirror.stores`` on the
composite ``(tenant_id, store_id)`` — null when the store is unmirrored. That store-side tenant
predicate is MANDATORY (``identity_mirror`` is RLS-OFF, D41; it is the store table's only tenant
isolation). The pattern is copied inline from ``repos/runs.py`` — no shared helper is extracted
(deferred pending identity_mirror RLS-on; D70 re-opened as D126). The join preserves row count
(``stores`` PK ``(tenant_id, store_id)`` ⇒ at most one match).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Row, Select, and_, select
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.errors import TenantScopeError
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.db import read_session
from dis_ui_server.models import StoreRow, StoreSkuCurrentPosition

# The list projection: the FULL live column set of store_sku_current_position EXCEPT
# tenant_id (scope, never on the wire) and ingest_metadata (operator-excluded) — 43 columns, in
# live-schema ordinal order. store_name is NOT here; it is projected from the identity_mirror.stores
# join below. mapping_version_id is selected as the SOURCE of the wire's mapping_version alias
# (handlers/canonical.py) — it is not exposed under its own key. Every name must be a mapped
# attribute on StoreSkuCurrentPosition (getattr, below) and have a StoreSkuPositionRow field +
# _to_row mapping — the three sites stay in lockstep (a mismatch is a test failure, not a prod drop).
_LIST_COLUMNS = (
    "id",
    "store_id",
    "sku_id",
    "sku_variant",
    "sku_lot_batch",
    "barcode",
    "product_name",
    "product_description",
    "product_category",
    "product_sub_category",
    "product_department",
    "supplier_id",
    "packaging_type",
    "sku_size",
    "unit_of_measure",
    "current_retail_price",
    "unit_cost",
    "promo_price",
    "promo_identifier",
    "yesterday_retail_price",
    "tax_treatment",
    "stock_qty",
    "lead_time_days",
    "expiry_date",
    "receipt_date",
    "expiry_source",
    "expiry_confidence",
    "regulatory_flag",
    "regulatory_type",
    "currency",
    "reorder_point",
    "sku_status",
    "velocity_7day",
    "stock_age_days",
    "unit_cost_trend_30day",
    "attribute_staleness_map",
    "current_retail_price_changed_at",
    "product_name_changed_at",
    "last_source_event_at",
    "mapping_version_id",
    "trace_id",
    "dis_channel",
    "last_updated_at",
)


def _tenant_term(scope: ReadScope) -> list[ColumnElement[bool]]:
    """The in-query tenant predicate: applied for a pinned (TENANT) scope, OMITTED
    for PLATFORM see-all (the RLS USING branch is the see-all isolation).

    Conditioned on ``scope.is_platform``, NEVER on ``tenant_id`` being absent — so a TENANT scope
    ALWAYS carries the predicate (the catastrophe invariant). canonical.tenant_id is NOT NULL, so
    there is no system-row edge case; for PLATFORM the policy widens reads and the predicate must
    not re-pin.
    """
    if scope.is_platform:
        return []
    if scope.tenant_id is None:  # unreachable: a pinned scope always carries a UUID
        raise TenantScopeError("a pinned read scope carries no tenant", tenant_id=None)
    return [StoreSkuCurrentPosition.tenant_id == scope.tenant_id]


def _filters(
    scope: ReadScope,
    *,
    store_id: UUID | None,
    sku: str | None,
) -> list[ColumnElement[bool]]:
    """The WHERE terms (tenant predicate first, when pinned)."""
    terms: list[ColumnElement[bool]] = _tenant_term(scope)
    if store_id is not None:
        terms.append(StoreSkuCurrentPosition.store_id == store_id)
    if sku is not None and sku != "":
        # Contains-search on the SKU id (the search box). ILIKE is fine at the bounded sample
        # size; the escape keeps % / _ in the term literal, not wildcards.
        escaped = sku.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        terms.append(StoreSkuCurrentPosition.sku_id.ilike(f"%{escaped}%", escape="\\"))
    return terms


def _build_statement(
    scope: ReadScope,
    *,
    limit: int,
    store_id: UUID | None,
    sku: str | None,
) -> Select[Any]:
    """The SELECT for the positions list: the 43-column projection + the store_name join.

    Extracted so the store-side tenant predicate is inspectable without a DB (the criterion-6
    structural test compiles this and fails if the ``StoreRow.tenant_id ==
    StoreSkuCurrentPosition.tenant_id`` term is ever removed — that predicate is the ONLY tenant
    isolation on the RLS-OFF store table, D41, so it has no behavioural signature to assert on).
    """
    columns = [getattr(StoreSkuCurrentPosition, name) for name in _LIST_COLUMNS]
    return (
        select(*columns, StoreRow.name.label("store_name"))
        .select_from(StoreSkuCurrentPosition)
        .outerjoin(
            StoreRow,
            and_(
                # MANDATORY store-side tenant predicate: identity_mirror is RLS-OFF, so this
                # composite (tenant_id, store_id) match is the ONLY tenant isolation on the store
                # table. Defense-in-depth here (store_id is globally unique via uq_ims_store_id and
                # the base rows are already RLS-forced) but it CANNOT be omitted — copied inline from
                # the runs pattern; no shared helper is extracted.
                StoreRow.tenant_id == StoreSkuCurrentPosition.tenant_id,
                StoreRow.store_id == StoreSkuCurrentPosition.store_id,
            ),
        )
        .where(*_filters(scope, store_id=store_id, sku=sku))
        .order_by(StoreSkuCurrentPosition.last_updated_at.desc(), StoreSkuCurrentPosition.id.desc())
        .limit(limit)
    )


async def list_positions(
    engine: AsyncEngine,
    scope: ReadScope,
    *,
    limit: int,
    store_id: UUID | None = None,
    sku: str | None = None,
) -> Sequence[Row[Any]]:
    """The tenant's canonical positions (newest first), filtered, bounded to ``limit``.

    TENANT sees its own (canonical RLS + the predicate); PLATFORM see-all reads across every
    tenant via the policy USING branch. ``last_updated_at DESC`` with ``id`` (UUIDv7,
    time-ordered) as the stable tie-breaker; ``limit`` bounds the high-volume table. store_name is
    LEFT-joined from identity_mirror.stores (see :func:`_build_statement`).
    """
    statement = _build_statement(scope, limit=limit, store_id=store_id, sku=sku)
    async with read_session(engine, is_platform=scope.is_platform, tenant_id=scope.tenant_id) as conn:
        return list((await conn.execute(statement)).all())


__all__ = ["list_positions"]
