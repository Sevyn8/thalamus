"""``GET /stores-onboarded`` — the token tenant's mirrored stores.

Tenant from the verified token ONLY (no path/query parameter exists, so none
can be honoured); the read goes through the single ``repos/stores.py``
chokepoint that owns the in-query tenant predicate (``identity_mirror`` is
RLS-OFF, D41 — the registered weak link). Tenant-facing only; the ops
cross-tenant store read is a later endpoint.
"""

from __future__ import annotations

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.errors import TenantScopeError
from dis_ui_server.auth.identity import Identity
from dis_ui_server.auth.scope import ReadScope, require_read_scope, require_tenant, tenant_uuid_of
from dis_ui_server.repos.stores import list_onboarded_stores
from dis_ui_server.schemas.stores import OnboardedStore, StoreStatus, StoreTaxTreatment

router = APIRouter()

# §2.6: the BFF owns vocabulary translation; DB vocab never leaks. Explicit maps
# (not ``.lower()``) so a NEW database vocabulary member fails loud (KeyError →
# 500) instead of silently leaking an untranslated value to the UI.
_STATUS_WIRE: dict[str, StoreStatus] = {
    "OPENING": "opening",
    "ACTIVE": "active",
    "INACTIVE": "inactive",
    "CLOSED": "closed",
}
_TAX_TREATMENT_WIRE: dict[str, StoreTaxTreatment] = {
    "INCLUSIVE": "inclusive",
    "EXCLUSIVE": "exclusive",
}


def _to_wire(row: Row[Any]) -> OnboardedStore:
    return OnboardedStore(
        store_id=str(row.store_id),
        name=row.name,
        store_code=row.store_code,
        status=_STATUS_WIRE[row.status],
        country=row.country,
        timezone=row.timezone,
        currency=row.currency,
        tax_treatment=_TAX_TREATMENT_WIRE[row.tax_treatment],
    )


@router.get("/stores-onboarded")
async def get_stores_onboarded(
    request: Request,
    identity: Annotated[Identity, Depends(require_tenant)],
) -> list[OnboardedStore]:
    """The tenant's onboarded stores, stable order (name, store_id); bare array."""
    engine: AsyncEngine = request.app.state.engine
    rows = await list_onboarded_stores(engine, tenant_uuid_of(identity))
    return [_to_wire(row) for row in rows]


@router.get("/stores-onboarded/for-tenant/{tenant_id}")
async def get_stores_onboarded_for_tenant(
    request: Request,
    tenant_id: UUID,
    scope: Annotated[ReadScope, Depends(require_read_scope)],
) -> list[OnboardedStore]:
    """An acted-for tenant's onboarded stores, for a PLATFORM ops caller (the cross-tenant
    counterpart of ``GET /stores-onboarded``, promised as "a later endpoint" above).

    ``/stores-onboarded`` is token-tenant-pinned; a PLATFORM ops caller carries no tenant
    claim, so the acted-for tenant rides the PATH — the read-side analog of the write
    impersonation, honoured ONLY on a PLATFORM + ``dis:ops`` token.
    ``require_read_scope`` yields ``is_platform`` True for exactly that posture (PLATFORM
    without ``dis:ops`` is already a 403 there); a TENANT caller has no business on this
    cross-tenant surface (it uses ``/stores-onboarded``), so it is refused 403. The read still
    goes through the single ``repos/stores.py`` chokepoint that owns the in-query tenant
    predicate — here scoped to the acted-for tenant.
    """
    if not scope.is_platform:
        raise TenantScopeError(
            "cross-tenant store read requires a PLATFORM ops caller",
            tenant_id=None,
        )
    engine: AsyncEngine = request.app.state.engine
    rows = await list_onboarded_stores(engine, tenant_id)
    return [_to_wire(row) for row in rows]
