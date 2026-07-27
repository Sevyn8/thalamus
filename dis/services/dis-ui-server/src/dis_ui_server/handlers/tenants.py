"""``GET /tenants-actable`` — the tenants a PLATFORM ops caller may act for.

WHY THIS ENDPOINT EXISTS. The connect journeys let a PLATFORM ops caller onboard a source
ON BEHALF OF a tenant (``resolve_acted_for``, Slice 17b / D92), so the UI has to offer a
tenant to act for. It used to derive that list from ``GET /sources`` — distinct tenants
among the rows — which silently made the list "every tenant that ALREADY HAS a source".
That is the exact complement of the onboarding case: a freshly onboarded tenant with zero
sources could never be picked, so nobody could connect its FIRST source. The list has to
come from the tenant mirror, not from a by-product of another read.

THE QUERY CARRIES NO TENANT PREDICATE. ``identity_mirror`` is RLS-OFF (D41) and
``repos.tenants.list_actable_tenants`` is unpredicated by design — an all-tenants list is
the point of it. Its replacement is a ``scope.is_platform`` assertion, and that assertion
lives in TWO places on purpose:

- In the repo, which takes the ``ReadScope`` and refuses a non-PLATFORM one itself. That is
  the durable one: it travels with the query, so a future caller cannot lose it.
- Here, before any DB connection is opened, in the same position as the gate on
  ``GET /stores-onboarded/for-tenant/{tenant_id}``.

``require_read_scope`` yields ``is_platform`` True only for PLATFORM + ``dis:ops`` (a
PLATFORM token without the role is already 403 there); a TENANT caller has no acted-for
tenant to choose and is refused 403.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.errors import TenantScopeError
from dis_ui_server.auth.scope import ReadScope, require_read_scope
from dis_ui_server.repos.tenants import list_actable_tenants
from dis_ui_server.schemas.tenants import ActableTenant, TenantStatus

router = APIRouter()

# §2.6: the BFF owns vocabulary translation; DB vocab never leaks. An explicit map (not
# ``.lower()``) so a NEW database vocabulary member fails loud (KeyError → 500) instead of
# leaking untranslated. TERMINATED is absent because the repo filters it out — if that filter
# regresses, this map is where it stops.
_STATUS_WIRE: dict[str, TenantStatus] = {
    "ONBOARDING": "onboarding",
    "TRIAL": "trial",
    "ACTIVE": "active",
    "SUSPENDED": "suspended",
}


def _to_wire(row: Row[Any]) -> ActableTenant:
    return ActableTenant(
        tenant_id=str(row.tenant_id),
        name=row.name,
        display_code=row.display_code,
        status=_STATUS_WIRE[row.status],
    )


@router.get("/tenants-actable")
async def get_tenants_actable(
    request: Request,
    scope: Annotated[ReadScope, Depends(require_read_scope)],
) -> list[ActableTenant]:
    """Every non-TERMINATED mirrored tenant, ordered by name; bare array.

    PLATFORM ops only. ``suspended`` tenants ARE returned, carrying their status — the
    caller renders them unselectable rather than having them vanish, because an absent row
    explains nothing and "what a suspended tenant may do" is not settled here.

    The list is only as complete as ``identity_mirror.tenants``; mirror-sync-consumer is not
    deployed, so today it reflects the hand-seeded rows.
    """
    if not scope.is_platform:
        # The outer half of the two-place gate (see the module docstring). The repo asserts
        # the same thing; this one resolves before a connection is opened.
        raise TenantScopeError(
            "the actable-tenant list requires a PLATFORM ops caller",
            tenant_id=None,
        )
    engine: AsyncEngine = request.app.state.engine
    rows = await list_actable_tenants(engine, scope)
    return [_to_wire(row) for row in rows]
