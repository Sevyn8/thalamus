"""``config.sources`` reads + writes — the source registry data access (Phase A, D112).

The FIRST writable table dis-ui-server owns in the shared DB. Writes go through
``write_session`` (the two-GUC WITH CHECK pins the row to the acted-for tenant); reads go
through ``read_session``. CORE-STYLE execution on the dis-rls connection (service CLAUDE.md
durable invariant) — never an ``AsyncSession``, never a ``.commit()`` (the session owns the
transaction). Mirrors ``repos/mapping_templates.py`` (the create_template write path).

IntegrityError is translated NARROWLY (rule 6): a duplicate ``(tenant_id, source_id)`` PK ->
``SourceAlreadyExistsError`` (409); a tenant-FK miss (token tenant not mirrored) ->
``TenantScopeError`` (403, consistent with the no-oracle read posture). Any OTHER
IntegrityError re-raises (a NOT NULL / CHECK-vocab violation is a bug, a 500).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import ColumnElement, Row, insert, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.errors import SourceAlreadyExistsError, TenantScopeError
from dis_ui_server.auth.identity import UserType
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.db import read_session, write_session
from dis_ui_server.models import Source, TenantRow

# Bounded list — the registry is small per tenant, but bound it like the other lists.
_LIST_LIMIT = 500

_PK_CONSTRAINT = "pk_config_sources"
_TENANT_FK_CONSTRAINT = "fk_config_sources_tenant"


def _violates(exc: IntegrityError, constraint: str) -> bool:
    """True when the wrapped psycopg error names exactly this constraint."""
    diag = getattr(exc.orig, "diag", None)
    return diag is not None and getattr(diag, "constraint_name", None) == constraint


def _tenant_term(scope: ReadScope) -> list[ColumnElement[bool]]:
    """The in-query tenant predicate (Slice 17b): applied for a pinned (TENANT) scope,
    OMITTED for PLATFORM see-all. Conditioned on ``is_platform``, never on tenant-absence."""
    if scope.is_platform:
        return []
    if scope.tenant_id is None:  # unreachable: a pinned scope always carries a UUID
        raise TenantScopeError("a pinned read scope carries no tenant", tenant_id=None)
    return [Source.tenant_id == scope.tenant_id]


async def list_sources(engine: AsyncEngine, scope: ReadScope) -> Sequence[Row[Any]]:
    """The tenant's registered sources (ordered by source_id). TENANT sees its own;
    PLATFORM see-all reads across every tenant via the policy USING branch."""
    statement = (
        select(
            Source.tenant_id,  # projected for fleet attribution (Chunk 1); already on the FROM table
            TenantRow.name.label("tenant_name"),  # LEFT JOIN identity_mirror.tenants (Chunk 9)
            Source.source_id,
            Source.display_name,
            Source.channel,
            Source.store_id,
            Source.schedule,
            Source.status,
            Source.created_at,
            Source.updated_at,
        )
        .select_from(Source)
        # LEFT JOIN identity_mirror.tenants on the tenant PK (≤1 match, no fan-out); RLS-OFF table
        # (D41), read under the existing read_session. LEFT so an unmirrored tenant → NULL name.
        .outerjoin(TenantRow, TenantRow.tenant_id == Source.tenant_id)
        .where(*_tenant_term(scope))
        .order_by(Source.source_id)
        .limit(_LIST_LIMIT)
    )
    async with read_session(engine, is_platform=scope.is_platform, tenant_id=scope.tenant_id) as conn:
        return list((await conn.execute(statement)).all())


async def create_source(
    engine: AsyncEngine,
    tenant_id: UUID,
    *,
    source_id: str,
    display_name: str,
    channel: str | None,
    store_id: str | None,
    schedule: str | None,
    created_by_user_id: UUID | None,
    user_type: UserType,
) -> Row[Any]:
    """Insert one source row for the acted-for tenant; returns the created row.

    The two-GUC WITH CHECK pins ``tenant_id`` to the acted-for tenant (a PLATFORM actor cannot
    write another tenant than the one ``resolve_acted_for`` decided). A duplicate PK is a clean
    409; a tenant not mirrored in identity_mirror is a 403.
    """
    statement = (
        insert(Source)
        .values(
            tenant_id=tenant_id,
            source_id=source_id,
            display_name=display_name,
            channel=channel,
            store_id=store_id,
            schedule=schedule,
            status="active",
            created_by_user_id=created_by_user_id,
        )
        .returning(
            Source.tenant_id,  # RETURNING it too: the shared _to_row builds SourceRow (Chunk 1)
            # Chunk 9: a READ-ONLY scalar so the create echo carries the SAME tenant_name the
            # list does (the shared _to_row reads row.tenant_name on both paths). Projection
            # only — no change to insert/write semantics. NULL if unmirrored.
            #
            # MATCHED AGAINST THE BIND, NOT AGAINST Source.tenant_id, AND THAT IS LOAD-BEARING.
            # A RETURNING clause has no enclosing FROM for the insert target, so SQLAlchemy
            # cannot correlate to it: an earlier `.where(TenantRow.tenant_id ==
            # Source.tenant_id).correlate(Source)` compiled `.correlate()` to a no-op and
            # auto-added config.sources to the SUBQUERY's own FROM. That is a cross join, so
            # the scalar subquery returned one row per source the tenant already had and
            # Postgres raised CardinalityViolation — a 500 on every genuinely new source once
            # a tenant had two or more. It hid because createSourceIfAbsent trips the unique
            # constraint first, so re-registering an EXISTING source 409s before RETURNING is
            # ever evaluated.
            #
            # tenant_id is already a bind on this INSERT, so matching it directly needs no
            # correlation at all. Do not reintroduce one here.
            select(TenantRow.name)
            .where(TenantRow.tenant_id == tenant_id)
            .scalar_subquery()
            .label("tenant_name"),
            Source.source_id,
            Source.display_name,
            Source.channel,
            Source.store_id,
            Source.schedule,
            Source.status,
            Source.created_at,
            Source.updated_at,
        )
    )
    async with write_session(engine, is_platform=user_type is UserType.PLATFORM, acted_for=tenant_id) as conn:
        try:
            result = await conn.execute(statement)
        except IntegrityError as exc:
            if _violates(exc, _PK_CONSTRAINT):
                raise SourceAlreadyExistsError(
                    f"source {source_id!r} already exists for this tenant",
                    tenant_id=str(tenant_id),
                    source_id=source_id,
                ) from exc
            if _violates(exc, _TENANT_FK_CONSTRAINT):
                raise TenantScopeError(
                    "token tenant is not provisioned in DIS (no identity_mirror row)",
                    tenant_id=str(tenant_id),
                ) from exc
            raise
        return result.one()


__all__ = ["create_source", "list_sources"]
