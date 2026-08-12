"""Step 6.22: the Python `PermissionResource` enum and Postgres `resource_enum` must agree.

This is the check whose ABSENCE let `ModuleCode` diverge. `module_code_enum` carries 7 values in
Postgres against 6 in Python: ROOS was retired from the Python vocabulary on 2026-05-12 and left
in the database type, and nothing noticed because nothing compared them. The drift is documented
in FN-AB-44 and is harmless only because no live row carries the extra value.

`resource_enum` gained its first new value ever in this step (CHANNELS), which is the right
moment to make that class of drift impossible for this enum. A member added on one side and not
the other fails here rather than at the first INSERT that uses it.

===============================================================================================
DELIBERATELY SCOPED TO resource_enum, AND THE REASON IS NOT TIMIDITY
===============================================================================================
Generalising the same assertion over `module_code_enum` WOULD FAIL TODAY, because of the ROOS
divergence above. Two responses were available and only one is honest:

  - Weaken the assertion (allow the DB to be a superset) so it passes on both enums. That turns
    a parity test into a one-directional test and would have caught neither half of the drift it
    exists to prevent.
  - Scope it to the enum that IS in parity, state why the other is excluded, and leave FN-AB-44
    to close the divergence on its own terms.

The second is what this file does. When FN-AB-44 lands the migration that retires ROOS from
`module_code_enum`, extend `_ENUM_PAIRS` with that pair and this test starts guarding it too.
The one-line addition is the whole cost, which is the point of keeping the pair list as data.

`action_enum` and `permission_scope_enum` are in parity today and are included: they cost nothing
to guard and both are locked vocabularies whose next change is exactly the event worth catching.
"""

from __future__ import annotations

from enum import Enum

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from admin_backend.config import get_settings
from admin_backend.models.permission import (
    PermissionAction,
    PermissionResource,
    PermissionScope,
)

# (Postgres type name, Python enum) pairs that MUST agree exactly, in both directions.
#
# module_code_enum IS ABSENT ON PURPOSE. See the module docstring: it is out of parity today
# (7 values in Postgres, 6 in Python, differing by ROOS) and adding it here would fail rather
# than guard. FN-AB-44 tracks the migration that closes it; add the pair in the same commit.
_ENUM_PAIRS: list[tuple[str, type[Enum]]] = [
    ("resource_enum", PermissionResource),
    ("action_enum", PermissionAction),
    ("permission_scope_enum", PermissionScope),
]

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

    ROOS lives in `module_code_enum` and not in `ModuleCode`, and the failure mode is documented
    in that enum's own docstring: any row carrying the DB-only value crashes Pydantic validation
    at the read boundary. A one-directional test would have passed throughout.
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
