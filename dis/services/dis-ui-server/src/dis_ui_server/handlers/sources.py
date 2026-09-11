"""``GET /sources`` + ``POST /sources`` — the source registry (Phase A, D112).

The FIRST write endpoint dis-ui-server owns over a table it also created. POST mirrors
``POST /mapping-templates``: ``require_write_scope`` + ``resolve_acted_for`` decide the
acted-for tenant (TENANT pins its own; a body-named tenant is 403; PLATFORM+``dis:ops`` writes
the acted-for tenant), the request is validated by Pydantic before any DB touch, and the repo
write rides ``write_session`` whose two-GUC WITH CHECK pins the row to that tenant. GET is the
tenant-scoped list via ``require_read_scope`` / ``read_session``.

Wire<->DB: ISO timestamps here; the repo speaks DB vocabulary. ``channel`` is passthrough
(DB value == wire value). Reuses existing errors (SourceAlreadyExistsError -> 409, the scope
errors) — no HTTPException in business logic.
"""

from __future__ import annotations

from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy import Row
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_ui_server.auth.identity import Identity
from dis_ui_server.auth.scope import (
    ReadScope,
    WriteScope,
    get_current_identity,
    require_read_scope,
    require_write_scope,
    resolve_acted_for,
)
from dis_ui_server.repos.sources import create_source, list_sources
from dis_ui_server.schemas.sources import SourceCreate, SourceListResponse, SourceRow

router = APIRouter()


def _iso(value: datetime) -> str:
    """ISO-8601 with the UTC offset rendered as ``Z`` (the wire convention)."""
    return value.isoformat().replace("+00:00", "Z")


def _created_by_uuid(identity: Identity) -> UUID | None:
    """The token ``sub`` as a UUID where it is one; NULL otherwise (mirrors the templates
    handler — the real claim vocabulary is unsigned, D56)."""
    try:
        return UUID(identity.user_id)
    except ValueError:
        return None


def _to_row(row: Row[Any]) -> SourceRow:
    return SourceRow(
        tenant_id=str(row.tenant_id),  # NOT NULL on config.sources — always present
        tenant_name=row.tenant_name,  # Chunk 9: identity_mirror.tenants.name (LEFT JOIN; may be null)
        source_id=row.source_id,
        display_name=row.display_name,
        channel=row.channel,
        store_id=row.store_id,
        schedule=row.schedule,
        status=row.status,
        created_at=_iso(row.created_at),
        updated_at=_iso(row.updated_at),
    )


@router.get("/sources")
async def list_registered_sources(
    request: Request,
    scope: Annotated[ReadScope, Depends(require_read_scope)],
) -> SourceListResponse:
    """The tenant's registered sources. TENANT sees its own; PLATFORM (user_type=PLATFORM +
    dis:ops) sees cross-tenant."""
    engine: AsyncEngine = request.app.state.engine
    rows = await list_sources(engine, scope)
    return SourceListResponse(items=[_to_row(r) for r in rows])


@router.post("/sources", status_code=201)
async def create_registered_source(
    request: Request,
    identity: Annotated[Identity, Depends(get_current_identity)],
    write_scope: Annotated[WriteScope, Depends(require_write_scope)],
    body: SourceCreate,
) -> SourceRow:
    """Register a source. Acted-for tenant discriminated by the VERIFIED user_type:
    TENANT pins to its token tenant (a body acting_for is 403); PLATFORM+dis:ops writes the
    body's acted-for tenant; a duplicate (tenant_id, source_id) is 409."""
    engine: AsyncEngine = request.app.state.engine
    acted_for = resolve_acted_for(write_scope, body.acting_for_tenant_id)
    row = await create_source(
        engine,
        acted_for,
        source_id=body.source_id,
        display_name=body.display_name,
        channel=body.channel,
        store_id=body.store_id,
        schedule=body.schedule,
        created_by_user_id=_created_by_uuid(identity),
        user_type=write_scope.user_type,
    )
    return _to_row(row)
