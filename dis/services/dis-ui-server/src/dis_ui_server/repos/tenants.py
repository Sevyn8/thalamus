"""``identity_mirror.tenants`` reads — the ONLY module that queries ``TenantRow``.

``identity_mirror`` is RLS-OFF (D41): there is no database backstop, so isolation on this
table is whatever the caller supplies. That is why every read of the model lives here.

TWO POSTURES LIVE IN THIS MODULE, and the difference is deliberate — read it before adding
a third function:

- ``get_tenant_display_code`` is TENANT-SCOPED. The explicit ``WHERE tenant_id = <token
  tenant>`` is the only isolation, exactly the registered ``repos/stores.py`` posture. Its
  predicate and its target are the same id, so no cross-tenant read is expressible through
  it.

- ``list_actable_tenants`` is CROSS-TENANT BY DESIGN and carries NO tenant predicate — an
  all-tenants list is the entire point of it. Isolation here is not absent, it is
  RELOCATED: the control is a ``scope.is_platform`` assertion, and the function ASSERTS IT
  ITSELF rather than trusting its caller. That placement is deliberate. With no predicate
  and an RLS-OFF table, a single ``if`` in a single handler would be the only thing between
  this query and every tenant name in the fleet — and a test can pin today's caller, never
  the next one. The guarantee travels with the function, so a future caller that forgets
  the gate gets a 403 instead of a leak. ``handlers/tenants.py`` keeps its own gate too:
  defence in depth, and it refuses before any DB connection is opened.

  Do not copy this no-predicate shape into a tenant-facing read.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import Row, select
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.errors import TenantScopeError
from dis_rls import rls_session
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.db import read_session
from dis_ui_server.models import TenantRow

# Bounded like the other lists. The beta fleet is single digits, so this is a runaway guard
# rather than pagination — if it is ever reached, the list needs the keyset treatment (D124),
# not a bigger number.
_LIST_LIMIT = 500

# The mirror's CHECK vocabulary is ONBOARDING | TRIAL | ACTIVE | SUSPENDED | TERMINATED.
# TERMINATED is excluded HERE and nowhere else: it is an end state, so there is no onboarding
# left to act for. SUSPENDED is deliberately RETURNED, not filtered — what a suspended tenant
# may do is unsettled in this system, and a filter here would quietly answer it. The status
# rides the wire instead and the picker disables the row, so the policy sits in one visible
# place and can move without touching this endpoint.
_END_STATE_STATUS = "TERMINATED"


async def get_tenant_display_code(engine: AsyncEngine, tenant_id: UUID) -> str | None:
    """The token tenant's ``display_code``, or ``None`` (mirror-NULL or unmirrored).

    Readability only (D52: codes are never a substitute for the UUID), so an
    absent value is not an error — the producer simply omits the optional wire
    field. ``tenant_id`` MUST come from the verified token (``tenant_uuid_of``).
    """
    statement = select(TenantRow.display_code).where(
        TenantRow.tenant_id == tenant_id  # the in-query scoping (D41) — do not remove
    )
    async with rls_session(engine, tenant_id) as conn:
        return (await conn.execute(statement)).scalar_one_or_none()


async def list_actable_tenants(engine: AsyncEngine, scope: ReadScope) -> Sequence[Row[Any]]:
    """Every non-TERMINATED mirrored tenant, ordered by name then ``tenant_id``.

    NO TENANT PREDICATE, deliberately — see the module docstring. Takes the ``ReadScope``
    and refuses a non-PLATFORM one HERE, so the isolation this query does not carry cannot
    be lost by a caller that forgets to gate.

    COMPLETENESS IS BOUNDED BY THE MIRROR. This returns what ``identity_mirror.tenants``
    holds, and mirror-sync-consumer is not deployed, so today that is the hand-seeded rows
    only. A tenant Customer Master knows about but the mirror does not is simply absent from
    the result — the fix is to sync the mirror, never to read Customer Master from here.
    """
    if not scope.is_platform:
        # The unpredicated query below is a full cross-tenant read; this is the predicate's
        # replacement, and it lives with the query so it cannot be left behind.
        raise TenantScopeError(
            "the actable-tenant list is a cross-tenant read; PLATFORM ops scope required",
            tenant_id=None,
        )
    statement = (
        select(
            TenantRow.tenant_id,
            TenantRow.name,
            TenantRow.display_code,
            TenantRow.status,
        )
        .where(TenantRow.status != _END_STATE_STATUS)
        .order_by(TenantRow.name, TenantRow.tenant_id)
        .limit(_LIST_LIMIT)
    )
    # PLATFORM see-all session: the GUCs are a no-op on an RLS-OFF table, but the session mode
    # must still follow the verified posture (a PLATFORM read never opens a TENANT-mode
    # session), and the engine's wrong-database / bypassing-role guard applies either way.
    async with read_session(engine, is_platform=True, tenant_id=None) as conn:
        return list((await conn.execute(statement)).all())


__all__ = ["get_tenant_display_code", "list_actable_tenants"]
