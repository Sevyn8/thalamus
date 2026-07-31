"""The ``current_state`` resolver: the only Synapse capability that resolves today.

THIS IS THE ONLY LAYER IN SYNAPSE THAT MAY NAME A CANONICAL TABLE. Everything else
reads its output. Enforcement is in two parts, and the second is the mechanism
rather than a nicety:

- import-linter forbids ``dis_canonical``, ``dis_rls`` and ``sqlalchemy`` to every
  ``synapse.*`` module EXCEPT ``synapse.resolvers``.
- a grep test fails if a canonical table name appears anywhere outside
  ``synapse/resolvers/``. That test is THE MECHANISM for the table-name half, not a
  belt: a table name is a string literal, and no import graph can see a string.

THREE DISTINCT JOBS, NONE OF THEM RESTATING CANONICAL'S DEFINITION:

  1. ``sqlalchemy.table()/column()`` NAMES the table. Lightweight constructs, not an
     ORM model — this module is not the schema of record and should not look like it.
     The only literals are the schema and table name.
  2. ``dis_canonical.StoreSkuCurrentPosition`` VALIDATES the shape. The column list
     for the SELECT is DERIVED from ``model_fields`` (verified: all 45 field names
     equal the DB column names exactly, no aliases), so the set of columns is stated
     once, in dis-canonical, and never here.
  3. ``CurrentStateRow`` (synapse.core) is the PROJECTION the capability returns.

WHY THE SELECT IS ALL 45 COLUMNS AND NOT THE ~12 THE PROJECTION USES. A narrow
select cannot be validated against the full model — the other 33 fields fail as
missing — so narrowing silently discards the loud-failure property that is the whole
point of validating. Reading 45 columns instead of 12 costs nothing at these volumes
(Postgres reads the row either way), and it buys the property that matters: a
canonical rename, drop or addition fails on the FIRST ROW rather than returning
something plausible for six months. ``StoreSkuCurrentPosition`` is
``extra='forbid'``, so an ADDED canonical column is caught too, not just a removed
one.

READ-ONLY, ALWAYS. Synapse never writes a DIS table. Nothing in this module builds
an INSERT/UPDATE/DELETE, and the engine it is handed should belong to a read-only
role (see the module docstring in ``synapse/resolvers/__init__.py`` on the deferred
``synapse_reader``).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sqlalchemy import column, select, table
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_canonical import StoreSkuCurrentPosition
from dis_rls import rls_session
from synapse.core.capability import CapabilityScope
from synapse.core.current_state import CurrentStateRow

# The ONE place a canonical table is named in Synapse. The column list is derived
# from the canonical model rather than typed out, so this construct cannot drift
# from dis-canonical: if the model gains or loses a field, the SELECT changes with
# it and the validation below still governs.
_CANONICAL_SCHEMA = "canonical"
_CURRENT_POSITION_TABLE = "store_sku_current_position"

_COLUMNS: tuple[str, ...] = tuple(StoreSkuCurrentPosition.model_fields)

_current_position = table(
    _CURRENT_POSITION_TABLE,
    *(column(name) for name in _COLUMNS),
    schema=_CANONICAL_SCHEMA,
)

# A runaway guard, not pagination. The beta fleet is single digits of tenants; if
# this is ever reached the caller needs a keyset design (DIS's D124 pattern), not a
# bigger number.
_MAX_ROWS = 5000


def _project(row: StoreSkuCurrentPosition) -> CurrentStateRow:
    """Project a VALIDATED canonical row down to the capability's return shape.

    Lives here rather than as a ``CurrentStateRow.from_canonical`` classmethod so that
    ``synapse.core`` imports nothing from dis-canonical and the import-linter contract
    forbidding it stays non-vacuous. Takes the validated MODEL, not a raw mapping, so
    the type signature is what guarantees the projection cannot be reached without the
    canonical validation having happened first.
    """
    # DDL-vs-MODEL DIVERGENCE, handled rather than papered over. The canonical DDL
    # declares last_updated_at NOT NULL DEFAULT NOW(), but dis-canonical types it
    # OPTIONAL because it is DB-generated and therefore absent on the WRITE path. On a
    # READ it is always populated, so the projection types it non-optional rather than
    # forcing every consumer to handle an impossible None. A None here means the row
    # did not come from a database read, which is a bug worth a loud error and not a
    # silently-nullable field.
    if row.last_updated_at is None:
        raise ValueError(
            "canonical row has a NULL last_updated_at, which the DDL declares NOT NULL; "
            "this row did not come from a database read"
        )
    return CurrentStateRow(
        tenant_id=row.tenant_id,
        store_id=row.store_id,
        sku_id=row.sku_id,
        product_name=row.product_name,
        product_category=row.product_category,
        sku_status=row.sku_status,
        current_retail_price=row.current_retail_price,
        unit_cost=row.unit_cost,
        promo_price=row.promo_price,
        stock_qty=row.stock_qty,
        reorder_point=row.reorder_point,
        currency=row.currency,
        expiry_date=row.expiry_date,
        last_source_event_at=row.last_source_event_at,
        last_updated_at=row.last_updated_at,
    )


def _validated(mapping: dict[str, Any]) -> StoreSkuCurrentPosition:
    """Validate one raw row against the canonical model.

    Deliberately NOT wrapped in a try/except. A validation failure here means
    canonical's shape moved underneath Synapse, and that must surface as a loud
    error on the first row — not a logged warning, not a skipped row, and above all
    not an empty result that reads as "this tenant has no inventory".
    """
    return StoreSkuCurrentPosition.model_validate(mapping)


async def resolve_current_state(
    engine: AsyncEngine,
    scope: CapabilityScope,
    *,
    store_id: UUID | None = None,
    limit: int = _MAX_ROWS,
) -> Sequence[CurrentStateRow]:
    """Resolve the current state of every SKU position in scope.

    ``scope`` carries the tenant and is the ONLY source of tenancy — never a caller
    field. It is required rather than defaulted: a resolver that silently defaults to
    a cross-tenant read is the failure this signature exists to prevent, so there is
    no default and no ``None`` case that quietly means "all tenants".

    ``store_id`` narrows within the scope's tenant. It cannot widen it: the RLS
    session is opened on the scope's tenant, so a store belonging to another tenant
    returns nothing rather than someone else's rows.

    Raises ``pydantic.ValidationError`` if canonical's shape has moved (see
    ``_validated``), and whatever ``dis_rls`` raises if the engine points at the
    wrong database or a role that can bypass RLS.
    """
    if limit > _MAX_ROWS:
        limit = _MAX_ROWS

    statement = select(*_current_position.c).where(
        # The in-query tenant predicate. Redundant with RLS by design, exactly as
        # DIS's own tenant-facing reads are: RLS is the floor, the predicate is the
        # statement of intent, and the two agreeing is what makes a future
        # RLS-off table (identity_mirror is one) not silently become a fleet read.
        _current_position.c.tenant_id == scope.tenant_id
    )
    if store_id is not None:
        statement = statement.where(_current_position.c.store_id == store_id)
    statement = statement.order_by(
        _current_position.c.store_id,
        _current_position.c.sku_id,
        _current_position.c.id,
    ).limit(limit)

    async with rls_session(engine, scope.tenant_id) as conn:
        rows = (await conn.execute(statement)).mappings().all()

    return [_project(_validated(dict(row))) for row in rows]


__all__ = ["resolve_current_state"]
