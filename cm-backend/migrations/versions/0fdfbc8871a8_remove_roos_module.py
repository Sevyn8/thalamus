"""remove_roos_module

Revision ID: 0fdfbc8871a8
Revises: b7e3c95a1d84
Create Date: 2026-09-11

Retire ROOS from ``module_code_enum`` and delete every row that references it.

Closes the FN-AB-44 divergence named in ``tests/integration/test_permission_enum_parity.py``:
``module_code_enum`` carried 7 values against ``ModuleCode``'s 6 because ROOS was retired from
the Python vocabulary on 2026-05-12 (``9462e11``) and left in the database type. The parity test
excluded this one enum for exactly that reason. This migration removes the exclusion's cause, and
the same commit adds the pair to ``_ENUM_PAIRS``.

After this migration the supported module set is exactly, in this order:

    PRICING_OS, PERISHABLES_ASSISTANT, PROMOTIONS_ASSISTANT, GOAL_CONSOLE, ADMIN, DIS

which is the pre-migration declaration order with ROOS (position 1) removed, and is identical to
``ModuleCode``'s member order. GOAL_CONSOLE is retained. No value is renamed and no ROOS row is
remapped onto another module — the rows are deleted.

===============================================================================================
THE PLATFORM GUC IS LOAD-BEARING, NOT CEREMONY
===============================================================================================
``tenant_module_access`` is ``ROW LEVEL SECURITY`` + ``FORCE ROW LEVEL SECURITY``, and FORCE
means the policy applies to the table OWNER too — which is the role migrations run as. Its
policy admits a row only when ``app.tenant_id`` matches or ``app.user_type = 'PLATFORM'``.
``env.py`` sets ``search_path`` and nothing else, so inside a migration NEITHER GUC is set and
the policy admits NOTHING. Measured on the development database before this migration was
written, as the non-superuser, non-bypassrls ``user_admin_backend`` role:

    SELECT count(*) FROM tenant_module_access;                       -> 0
    SET app.user_type='PLATFORM'; SELECT count(*) FROM ...;           -> 23

A ``DELETE ... WHERE module='ROOS'`` without the GUC therefore deletes zero rows AND a
verification ``SELECT`` afterwards returns zero rows, so the migration would report success
having done nothing, and the ``ALTER TYPE`` below would then fail (or worse, succeed against a
database whose ROOS rows were merely invisible). The ``set_config(..., true)`` call is
transaction-local; ``_assert_platform_guc_active`` proves it took effect rather than trusting it.

===============================================================================================
DEPENDENTS ARE DISCOVERED, NOT ASSUMED
===============================================================================================
The set of columns typed ``module_code_enum`` is read from ``pg_attribute`` at run time and
compared against the expected pair. A hard-coded list that is complete on the development
database and short by one in production is precisely the failure this shape refuses: an
unconverted column would keep a dangling dependency on the legacy type and ``DROP TYPE`` would
fail late, mid-migration. The same read reports column DEFAULTS; there are none today, and a
default would have to be dropped before the type change and restored after, so the migration
REFUSES rather than silently discarding one. Dependent views, materialized views and functions
are refused for the same reason — none exist, and ``DROP ... CASCADE`` is never used here.

Both dependent columns are NOT NULL with no default, so the ``USING column::text::new_type``
cast preserves NULL semantics trivially (there are no NULLs to preserve) and cannot encounter a
value outside the new type: every surviving value is one of the six, because the ROOS rows were
deleted first. ``ALTER COLUMN TYPE`` rebuilds dependent indexes and constraints automatically —
``uq_permissions_tuple`` (module, resource, action, scope) and
``uq_tenant_module_access_tenant_module`` (tenant_id, module) — which is the same property
``cec8fae734e0`` relied on when it re-pointed ``permissions.module`` at this type.

Delete order respects the FK graph without CASCADE: ``role_permissions`` -> ``permissions`` is
ON DELETE RESTRICT, so the child rows go first. ``lookups`` has no inbound FKs.

Forward-only, per the project's irreversible-enum convention (``d3f7a1c92b64``,
``90cd038ae618``, ``cec8fae734e0``, ``a1c4e7f09d2b``): ``downgrade()`` raises
NotImplementedError. Re-widening the enum is mechanically possible, but the deleted ROOS
catalogue, entitlement and permission rows cannot be reconstructed without an external source,
so a downgrade that restored only the label would misrepresent the database as recoverable.
Restore from backup if rollback is required.

Schema qualification: unqualified names per env.py's search_path SET inside the alembic
transaction (Step 3.0+ precedent).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0fdfbc8871a8"
down_revision: Union[str, Sequence[str], None] = "b7e3c95a1d84"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_ENUM = "module_code_enum"
_LEGACY_ENUM = "module_code_enum_legacy_roos"
_RETIRED = "ROOS"

# The supported set, in declaration order. Identical to ``ModuleCode``'s member order and to the
# pre-migration order minus ROOS, so no row's sort position changes relative to any other.
_SUPPORTED: tuple[str, ...] = (
    "PRICING_OS",
    "PERISHABLES_ASSISTANT",
    "PROMOTIONS_ASSISTANT",
    "GOAL_CONSOLE",
    "ADMIN",
    "DIS",
)

# (table, column) pairs expected to carry the enum. Verified against pg_attribute at run time;
# this is the assertion's expected value, not the list the migration works from.
_EXPECTED_COLUMNS: frozenset[tuple[str, str]] = frozenset(
    {("permissions", "module"), ("tenant_module_access", "module")}
)


def _assert_platform_guc_active(bind: sa.engine.Connection) -> None:
    """Prove the RLS escape hatch is in effect before any DML touches a FORCE-RLS table.

    Without this the deletes below are silent no-ops and every verification query agrees with
    them, because SELECT is filtered by the same policy. See the module docstring.
    """
    active = bind.execute(
        sa.text("SELECT current_setting('app.user_type', true)")
    ).scalar()
    if active != "PLATFORM":
        raise RuntimeError(
            "0fdfbc8871a8: app.user_type is "
            f"{active!r}, not 'PLATFORM'. tenant_module_access is FORCE RLS, so every "
            "DELETE and every verification SELECT below would operate on an empty row set "
            "and the migration would report success having removed nothing."
        )


def _dependent_columns(bind: sa.engine.Connection) -> list[tuple[str, str, str | None]]:
    """Every ordinary-table column typed ``module_code_enum``, with its DEFAULT expression."""
    rows = bind.execute(
        sa.text(
            """
            SELECT c.relname  AS table_name,
                   a.attname  AS column_name,
                   pg_get_expr(d.adbin, d.adrelid) AS default_expr
              FROM pg_attribute a
              JOIN pg_class     c ON c.oid = a.attrelid AND c.relkind = 'r'
              JOIN pg_namespace n ON n.oid = c.relnamespace
              JOIN pg_type      t ON t.oid = a.atttypid
              LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum
             WHERE t.typname = :enum
               AND n.nspname = current_schema()
               AND t.typnamespace = current_schema()::regnamespace
               AND a.attnum > 0
               AND NOT a.attisdropped
             ORDER BY c.relname, a.attname
            """
        ),
        {"enum": _ENUM},
    ).all()
    return [(r.table_name, r.column_name, r.default_expr) for r in rows]


def _assert_no_exotic_dependents(bind: sa.engine.Connection) -> None:
    """Refuse views, materialized views and functions that depend on the type.

    None exist. If one is ever added, converting the columns underneath it would either fail or
    silently leave the dependent pinned to the legacy type, and the only safe handling is to
    recreate it deliberately — which is a decision for whoever adds it, not a CASCADE here.
    """
    dependents = bind.execute(
        sa.text(
            """
            SELECT DISTINCT c.relname AS name, c.relkind::text AS kind
              FROM pg_depend d
              JOIN pg_class  c ON c.oid = d.refobjid
             WHERE d.refobjid IN (
                     SELECT oid FROM pg_type
                      WHERE typname = :enum
                        AND typnamespace = current_schema()::regnamespace)
               AND c.relkind IN ('v', 'm')
            """
        ),
        {"enum": _ENUM},
    ).all()
    functions = bind.execute(
        sa.text(
            """
            SELECT n.nspname || '.' || p.proname AS name
              FROM pg_proc p
              JOIN pg_namespace n ON n.oid = p.pronamespace
             WHERE p.prokind = 'f'
               AND n.nspname = current_schema()
               AND (p.prorettype = (SELECT oid FROM pg_type
                                     WHERE typname = :enum
                                       AND typnamespace = current_schema()::regnamespace)
                 OR (SELECT oid FROM pg_type
                      WHERE typname = :enum
                        AND typnamespace = current_schema()::regnamespace) = ANY (p.proargtypes))
            """
        ),
        {"enum": _ENUM},
    ).all()
    blocking = [f"{r.kind}:{r.name}" for r in dependents] + [f"f:{r.name}" for r in functions]
    if blocking:
        raise RuntimeError(
            f"0fdfbc8871a8: {_ENUM} has dependents this migration does not know how to "
            f"recreate: {sorted(blocking)}. Handle them explicitly — CASCADE would drop them."
        )


def upgrade() -> None:
    """Delete every ROOS row, then rebuild module_code_enum without the label."""
    bind = op.get_bind()

    # 0. Make FORCE-RLS rows visible to this transaction, and prove it worked.
    bind.execute(sa.text("SELECT set_config('app.user_type', 'PLATFORM', true)"))
    _assert_platform_guc_active(bind)

    # 1. Prove the dependent set is exactly what this migration converts, and that no column
    #    carries a DEFAULT that the type change would drop.
    found = _dependent_columns(bind)
    found_pairs = frozenset((table, column) for table, column, _ in found)
    if found_pairs != _EXPECTED_COLUMNS:
        raise RuntimeError(
            f"0fdfbc8871a8: columns typed {_ENUM} are {sorted(found_pairs)}, expected "
            f"{sorted(_EXPECTED_COLUMNS)}. Converting a partial set would leave a dangling "
            "dependency on the legacy type and DROP TYPE would fail mid-migration."
        )
    defaulted = [(t, c, d) for t, c, d in found if d is not None]
    if defaulted:
        raise RuntimeError(
            f"0fdfbc8871a8: {sorted((t, c) for t, c, _ in defaulted)} carry column DEFAULTs "
            f"({[d for _, _, d in defaulted]}). A default must be dropped before ALTER COLUMN "
            "TYPE and restored afterwards; refusing rather than discarding it silently."
        )
    _assert_no_exotic_dependents(bind)

    # 2. Delete ROOS rows in FK order. role_permissions -> permissions is ON DELETE RESTRICT,
    #    so the children go first. Counts are captured so step 3 can prove the deletes bit.
    before_permissions = bind.execute(
        sa.text("SELECT count(*) FROM permissions WHERE module::text <> :roos"),
        {"roos": _RETIRED},
    ).scalar_one()
    before_access = bind.execute(
        sa.text("SELECT count(*) FROM tenant_module_access WHERE module::text <> :roos"),
        {"roos": _RETIRED},
    ).scalar_one()

    bind.execute(
        sa.text(
            """
            DELETE FROM role_permissions
             WHERE permission_id IN (
                   SELECT id FROM permissions WHERE module::text = :roos)
            """
        ),
        {"roos": _RETIRED},
    )
    bind.execute(
        sa.text("DELETE FROM permissions WHERE module::text = :roos"), {"roos": _RETIRED}
    )
    bind.execute(
        sa.text("DELETE FROM tenant_module_access WHERE module::text = :roos"),
        {"roos": _RETIRED},
    )
    bind.execute(
        sa.text("DELETE FROM lookups WHERE list_name = 'module_code' AND code = :roos"),
        {"roos": _RETIRED},
    )

    # 3. No ROOS row survives, and nothing else was collateral. The second half is what makes
    #    the first half meaningful: "0 ROOS rows" is also what a fully-filtered row set reports.
    for table in ("permissions", "tenant_module_access"):
        remaining = bind.execute(
            sa.text(f"SELECT count(*) FROM {table} WHERE module::text = :roos"),
            {"roos": _RETIRED},
        ).scalar_one()
        if remaining:
            raise RuntimeError(f"0fdfbc8871a8: {remaining} ROOS rows survive in {table}.")
    stale_lookup = bind.execute(
        sa.text(
            "SELECT count(*) FROM lookups WHERE list_name = 'module_code' AND code = :roos"
        ),
        {"roos": _RETIRED},
    ).scalar_one()
    if stale_lookup:
        raise RuntimeError("0fdfbc8871a8: the ROOS module_code lookups row survives.")

    after_permissions = bind.execute(sa.text("SELECT count(*) FROM permissions")).scalar_one()
    after_access = bind.execute(
        sa.text("SELECT count(*) FROM tenant_module_access")
    ).scalar_one()
    if (after_permissions, after_access) != (before_permissions, before_access):
        raise RuntimeError(
            "0fdfbc8871a8: supported-module rows changed count during ROOS cleanup "
            f"(permissions {before_permissions} -> {after_permissions}, "
            f"tenant_module_access {before_access} -> {after_access}). Only ROOS rows may go."
        )

    # 4. Rename-recreate-cast. No CASCADE anywhere.
    op.execute(f"ALTER TYPE {_ENUM} RENAME TO {_LEGACY_ENUM}")
    labels = ", ".join(f"'{value}'" for value in _SUPPORTED)
    op.execute(f"CREATE TYPE {_ENUM} AS ENUM ({labels})")
    for table, column, _ in found:
        op.execute(
            f"ALTER TABLE {table} "
            f"ALTER COLUMN {column} TYPE {_ENUM} USING {column}::text::{_ENUM}"
        )
    op.execute(f"DROP TYPE {_LEGACY_ENUM}")

    # 5. End state: exactly the six supported labels, in order, and no legacy type left behind.
    final = [
        row[0]
        for row in bind.execute(
            sa.text(
                """
                SELECT e.enumlabel
                  FROM pg_type t
                  JOIN pg_enum e ON e.enumtypid = t.oid
                 WHERE t.typname = :enum
                   AND t.typnamespace = current_schema()::regnamespace
                 ORDER BY e.enumsortorder
                """
            ),
            {"enum": _ENUM},
        )
    ]
    if tuple(final) != _SUPPORTED:
        raise RuntimeError(f"0fdfbc8871a8: {_ENUM} ended as {final}, expected {list(_SUPPORTED)}.")
    leftover = bind.execute(
        sa.text("SELECT count(*) FROM pg_type WHERE typname = :legacy"),
        {"legacy": _LEGACY_ENUM},
    ).scalar_one()
    if leftover:
        raise RuntimeError(f"0fdfbc8871a8: {_LEGACY_ENUM} still exists after DROP TYPE.")


def downgrade() -> None:
    raise NotImplementedError(
        "remove_roos_module is forward-only. Re-adding the ROOS label would not restore the "
        "deleted ROOS lookups, permissions, role_permissions and tenant_module_access rows, "
        "which have no external source. Restore from backup if rollback is required. Mirrors "
        "the project's irreversible-enum convention (d3f7a1c92b64, 90cd038ae618, cec8fae734e0, "
        "a1c4e7f09d2b)."
    )
