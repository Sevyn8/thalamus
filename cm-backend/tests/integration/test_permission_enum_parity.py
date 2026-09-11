"""The Python permission/module enums and their Postgres types must agree, in both directions.

This is the check whose ABSENCE let `ModuleCode` diverge. `module_code_enum` carried 7 values in
Postgres against 6 in Python: ROOS was retired from the Python vocabulary on 2026-05-12 and left
in the database type, and nothing noticed because nothing compared them.

===============================================================================================
module_code_enum IS NOW GUARDED, WHICH IS THE POINT OF KEEPING THE PAIR LIST AS DATA
===============================================================================================
This file previously excluded `module_code_enum` and said so in a paragraph explaining that
generalising the assertion WOULD FAIL until a migration retired ROOS from the type. Migration
`0fdfbc8871a8` is that migration. The exclusion is gone and the pair is in `_ENUM_PAIRS`, so the
same two-directional assertion now covers it.

The alternative rejected at the time is still the one rejected now: weakening the assertion to
let the database be a superset of Python would have made both enums pass while catching neither
half of the drift the file exists to prevent.

`action_enum` and `permission_scope_enum` are locked vocabularies and are included: they cost
nothing to guard and their next change is exactly the event worth catching.

The ROOS-specific tests at the bottom are deliberately NOT subsumed by the parity pass. Parity
compares two lists, so it passes when BOTH sides are wrong together — a future edit that added
ROOS back to `ModuleCode` and to the type would keep parity green. Naming the retired value and
the six supported values explicitly is what distinguishes "the two sides agree" from "the two
sides agree and they agree on the right set".
"""

from __future__ import annotations

from enum import Enum

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from admin_backend.config import get_settings
from admin_backend.models.permission import (
    PermissionAction,
    PermissionResource,
    PermissionScope,
)
from admin_backend.models.tenant_module_access import ModuleCode

# (Postgres type name, Python enum) pairs that MUST agree exactly, in both directions.
_ENUM_PAIRS: list[tuple[str, type[Enum]]] = [
    ("resource_enum", PermissionResource),
    ("action_enum", PermissionAction),
    ("permission_scope_enum", PermissionScope),
    ("module_code_enum", ModuleCode),
]

# The supported module set, spelled out rather than derived from ModuleCode. Deriving it would
# make the assertion restate whatever Python happens to declare, so an accidental edit to the
# enum would edit its own test into agreement.
_SUPPORTED_MODULES: list[str] = [
    "PRICING_OS",
    "PERISHABLES_ASSISTANT",
    "PROMOTIONS_ASSISTANT",
    "GOAL_CONSOLE",
    "ADMIN",
    "DIS",
]

_RETIRED_MODULE = "ROOS"

# Schema-qualified, per CSD-03: pg_type is in pg_catalog, but the enum TYPE lives in the
# configured schema, so the namespace filter is what makes this read the right type rather than
# a same-named one somewhere else on the search_path.
_ENUM_VALUES = text(
    """
    SELECT e.enumlabel
      FROM pg_type t
      JOIN pg_enum e ON e.enumtypid = t.oid
      JOIN pg_namespace n ON n.oid = t.typnamespace
     WHERE t.typname = :type_name
       AND n.nspname = :schema
     ORDER BY e.enumsortorder
    """
)


async def _db_enum_values(engine: AsyncEngine, type_name: str) -> list[str]:
    schema = get_settings().db_schema
    async with engine.connect() as conn:
        rows = await conn.execute(_ENUM_VALUES, {"type_name": type_name, "schema": schema})
        return [row[0] for row in rows]


@pytest.mark.parametrize(("type_name", "python_enum"), _ENUM_PAIRS, ids=lambda v: getattr(v, "__name__", v))
async def test_the_database_enum_is_not_empty(
    engine: AsyncEngine, type_name: str, python_enum: type[Enum]
) -> None:
    """THE VACUITY GUARD, and it is not ceremony.

    `pg_type` returns no rows for a type name that does not exist in the configured schema, and
    an empty list compared against an empty list passes. A typo in `_ENUM_PAIRS`, a schema
    misconfiguration, or a renamed type would make every assertion below vacuously true while
    reading as coverage.
    """
    values = await _db_enum_values(engine, type_name)
    assert values, (
        f"{type_name} returned no values from pg_enum in schema {get_settings().db_schema!r}. "
        "Either the type does not exist under that name or the schema is wrong; every parity "
        "assertion below would pass having compared nothing."
    )


@pytest.mark.parametrize(("type_name", "python_enum"), _ENUM_PAIRS, ids=lambda v: getattr(v, "__name__", v))
async def test_every_python_member_exists_in_the_database_enum(
    engine: AsyncEngine, type_name: str, python_enum: type[Enum]
) -> None:
    """DIRECTION 1. A Python member the database does not know fails at the first INSERT that
    uses it, with a `psycopg.errors.InvalidTextRepresentation` deep inside a write path rather
    than a statement about the vocabulary."""
    in_db = set(await _db_enum_values(engine, type_name))
    in_python = {member.value for member in python_enum}

    missing = sorted(in_python - in_db)
    assert not missing, (
        f"{python_enum.__name__} declares {missing} which {type_name} does not carry. Add them "
        "with an ALTER TYPE ... ADD VALUE migration (see a1c4e7f09d2b for the autocommit-block "
        "idiom); a Python-only member is unwritable."
    )


@pytest.mark.parametrize(("type_name", "python_enum"), _ENUM_PAIRS, ids=lambda v: getattr(v, "__name__", v))
async def test_every_database_value_exists_in_the_python_enum(
    type_name: str, python_enum: type[Enum], engine: AsyncEngine
) -> None:
    """DIRECTION 2, AND IT IS THE ONE THAT ACTUALLY BIT.

    ROOS lived in `module_code_enum` and not in `ModuleCode` for four months, and the failure
    mode is the one `0fdfbc8871a8` removed: a row carrying a DB-only value crashes Pydantic
    validation at the read boundary. A one-directional test would have passed throughout.
    """
    in_db = set(await _db_enum_values(engine, type_name))
    in_python = {member.value for member in python_enum}

    orphaned = sorted(in_db - in_python)
    assert not orphaned, (
        f"{type_name} carries {orphaned} which {python_enum.__name__} does not declare. A row "
        "holding one of those values crashes validation at the read boundary. Either add the "
        "member to Python or retire it from Postgres with the rename-recreate-cast dance."
    )


async def test_channels_is_present_on_both_sides(engine: AsyncEngine) -> None:
    """THE VALUE THIS SLICE ADDED, asserted by name rather than only by the parity above.

    The parametrised tests would both pass if CHANNELS were absent from Python AND from
    Postgres, which is exactly the state before this migration ran. This is what distinguishes
    "the two sides agree" from "the two sides agree and the new value landed".
    """
    assert PermissionResource.CHANNELS.value == "CHANNELS"
    assert "CHANNELS" in set(await _db_enum_values(engine, "resource_enum"))


async def test_channels_is_last_in_both_declaration_orders(engine: AsyncEngine) -> None:
    """POSITION IS LOAD-BEARING, so it is asserted rather than trusted to a comment.

    Postgres orders an enum column by the type's declaration order and `ADD VALUE` without a
    BEFORE/AFTER clause appends. The permission list endpoints sort on the resource column, and
    `test_rbac_router.py::_permission_sort_tuple` recomputes that ordering from
    `PermissionResource`'s member positions to assert the two agree. If a future member is
    inserted mid-list in Python while `ADD VALUE` appends it in Postgres, the two orderings
    diverge and that test fails somewhere far from the cause. This one fails at the cause.
    """
    db_values = await _db_enum_values(engine, "resource_enum")
    python_values = [member.value for member in PermissionResource]

    assert db_values[-1] == "CHANNELS"
    assert python_values[-1] == "CHANNELS"
    assert db_values == python_values, (
        "resource_enum and PermissionResource agree on membership but not on ORDER. Postgres "
        "sorts enum columns by declaration order and the permission list endpoints sort on that "
        "column, so the two must match position for position, not merely as sets."
    )


# ===============================================================================================
# ROOS removal (migration 0fdfbc8871a8). Named values, not derived ones — see the module
# docstring on why parity alone would stay green if both sides regained ROOS together.
# ===============================================================================================
async def test_roos_is_absent_from_the_database_module_enum(engine: AsyncEngine) -> None:
    """The retired label is gone from the type itself, not merely unused by live rows."""
    values = await _db_enum_values(engine, "module_code_enum")
    assert values, "module_code_enum returned nothing; the assertion below would be vacuous."
    assert _RETIRED_MODULE not in values, (
        f"{_RETIRED_MODULE} is still a member of module_code_enum. Migration 0fdfbc8871a8 "
        "retires it with the rename-recreate-cast dance; an ALTER TYPE ... ADD VALUE that "
        "reintroduced it would be caught here."
    )


async def test_roos_is_absent_from_the_python_module_enum() -> None:
    """The same statement on the Python side, so the pair cannot drift back together."""
    assert _RETIRED_MODULE not in {member.value for member in ModuleCode}


async def test_exactly_the_six_supported_modules_remain(engine: AsyncEngine) -> None:
    """Membership AND order, on both sides, against a written-out list.

    GOAL_CONSOLE is in this list deliberately: it was dropped from the narrow `module_enum` by
    `90cd038ae618` and is a supported module today, so a removal pass that swept it up with ROOS
    fails here rather than in whatever renders the module cards.
    """
    db_values = await _db_enum_values(engine, "module_code_enum")
    python_values = [member.value for member in ModuleCode]

    assert db_values == _SUPPORTED_MODULES, (
        f"module_code_enum is {db_values}, expected {_SUPPORTED_MODULES}. Order is part of the "
        "assertion: Postgres sorts enum columns by declaration order."
    )
    assert python_values == _SUPPORTED_MODULES


async def test_no_legacy_module_enum_type_survives(engine: AsyncEngine) -> None:
    """The rename-recreate-cast dance leaves a renamed type behind if DROP TYPE is forgotten.

    A surviving `module_code_enum_legacy_roos` still carries ROOS, and any column accidentally
    left pointing at it would keep accepting the retired value while every assertion above,
    which reads `module_code_enum` by name, reported success.
    """
    schema = get_settings().db_schema
    async with engine.connect() as conn:
        leftovers = (
            await conn.execute(
                text(
                    """
                    SELECT t.typname
                      FROM pg_type t
                      JOIN pg_namespace n ON n.oid = t.typnamespace
                     WHERE n.nspname = :schema
                       AND t.typname LIKE 'module\\_code\\_enum\\_%'
                    """
                ),
                {"schema": schema},
            )
        ).all()
    assert not [row[0] for row in leftovers], (
        f"legacy module-code enum types survive: {[row[0] for row in leftovers]}"
    )


async def test_every_module_column_uses_the_current_enum_type(engine: AsyncEngine) -> None:
    """Both consumer columns point at the rebuilt type.

    This is the check that makes the one above meaningful in the other direction: the type can
    be correct while a column still references the legacy one.
    """
    schema = get_settings().db_schema
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    """
                    SELECT c.relname AS table_name, t.typname AS type_name
                      FROM pg_attribute a
                      JOIN pg_class c ON c.oid = a.attrelid AND c.relkind = 'r'
                      JOIN pg_namespace n ON n.oid = c.relnamespace
                      JOIN pg_type t ON t.oid = a.atttypid
                     WHERE n.nspname = :schema
                       AND a.attname = 'module'
                       AND a.attnum > 0
                       AND NOT a.attisdropped
                     ORDER BY c.relname
                    """
                ),
                {"schema": schema},
            )
        ).all()

    consumers = {row.table_name: row.type_name for row in rows}
    assert consumers == {
        "permissions": "module_code_enum",
        "tenant_module_access": "module_code_enum",
    }, f"module columns resolve to {consumers}"


async def test_the_retired_module_cannot_be_written(engine: AsyncEngine) -> None:
    """ROOS is refused by the database, and a supported value in the same shape is accepted.

    The second half is not padding. A refusal-only assertion cannot tell "ROOS was rejected
    because the label is gone" from "the INSERT was rejected because the statement, the schema
    or the connection is broken", and it would keep passing in all of those cases. The two
    INSERTs differ ONLY in the module value, so the contrast isolates the enum.

    Each INSERT gets its own connection: the connect-time ``SET search_path`` is itself
    transactional, so a rollback on a shared connection reverts it and the second statement
    would fail on an unresolved table name rather than testing anything. Names are
    schema-qualified per CSD-03 for the same reason.
    """
    schema = get_settings().db_schema
    insert = (
        f"INSERT INTO {schema}.permissions (module, resource, action, scope, code) "
        "VALUES (:module, 'WASTE_LOG', 'VIEW', 'TENANT', :code)"
    )

    async with engine.connect() as conn:
        with pytest.raises(DBAPIError) as rejected:
            await conn.execute(
                text(insert),
                {
                    "module": _RETIRED_MODULE,
                    "code": f"{_RETIRED_MODULE}.WASTE_LOG.VIEW.TENANT",
                },
            )
        assert "module_code_enum" in str(rejected.value), (
            "the INSERT failed for some reason other than the enum vocabulary: "
            f"{rejected.value}"
        )
        await conn.rollback()

    async with engine.connect() as conn:
        await conn.execute(
            text(insert),
            {"module": "GOAL_CONSOLE", "code": "GOAL_CONSOLE.WASTE_LOG.VIEW.TENANT"},
        )
        await conn.rollback()


async def test_no_live_row_references_the_retired_module(engine: AsyncEngine) -> None:
    """Catalogue, entitlement and permission rows are all clear of ROOS.

    Reads under the PLATFORM GUC on purpose: `tenant_module_access` is FORCE RLS, so without it
    the count is zero because the policy admits nothing, not because the cleanup worked.
    """
    schema = get_settings().db_schema
    async with engine.connect() as conn:
        await conn.execute(text("SELECT set_config('app.user_type', 'PLATFORM', true)"))

        visible = (
            await conn.execute(text(f"SELECT count(*) FROM {schema}.tenant_module_access"))
        ).scalar_one()
        assert visible > 0, (
            "tenant_module_access is empty under the PLATFORM GUC, so the ROOS count below "
            "proves nothing. Seed the database before trusting this test."
        )

        for table in ("permissions", "tenant_module_access"):
            remaining = (
                await conn.execute(
                    text(
                        f"SELECT count(*) FROM {schema}.{table} WHERE module::text = :module"
                    ),
                    {"module": _RETIRED_MODULE},
                )
            ).scalar_one()
            assert remaining == 0, f"{remaining} {_RETIRED_MODULE} rows survive in {table}"

        catalogue = (
            await conn.execute(
                text(
                    f"SELECT count(*) FROM {schema}.lookups "
                    "WHERE list_name = 'module_code' AND code = :module"
                ),
                {"module": _RETIRED_MODULE},
            )
        ).scalar_one()
        assert catalogue == 0, "the ROOS module_code lookups row survives"


async def test_the_module_catalogue_lists_exactly_the_supported_modules(
    engine: AsyncEngine,
) -> None:
    """The lookups catalogue is what the read endpoints render, so it is asserted separately.

    display_order stays at 2..7 rather than being renumbered: the values are aligned with cloud
    per the operator decision recorded in `test_rbac_router.py`, and the rendered sequence
    depends on their ORDER, not on them being contiguous.
    """
    schema = get_settings().db_schema
    async with engine.connect() as conn:
        rows = (
            await conn.execute(
                text(
                    f"SELECT code FROM {schema}.lookups WHERE list_name = 'module_code' "
                    "ORDER BY display_order"
                )
            )
        ).all()
    codes = [row[0] for row in rows]
    assert codes == [
        "GOAL_CONSOLE",
        "PRICING_OS",
        "PERISHABLES_ASSISTANT",
        "PROMOTIONS_ASSISTANT",
        "ADMIN",
        "DIS",
    ], f"module_code catalogue is {codes}"
    assert set(codes) == set(_SUPPORTED_MODULES)
