"""synapse.actions must look the same whether it was built from the DDL or reached by migrations.

WHY THIS EXISTS. ``schemas/postgres/actions.sql`` is the source of truth and migration 0001
applies it VERBATIM, so a FRESH database gets its columns from the DDL file. An EXISTING database
gets later columns from ``ALTER`` statements in migrations. Those are two paths to one schema and
nothing makes them agree — the DIS precedent (``0002_identity_mirror_codes``) keeps them in step
by hand: it ALTERs the table and also carries the columns in
``identity_mirror/tenants.sql``/``stores.sql``.

That hand-agreement is exactly the kind that drifts silently, and the drift is invisible until a
fresh deploy behaves differently from staging. So the two are compared here.

WHY IT IS A FILE COMPARISON AND NOT A DATABASE ONE. The obvious test is to migrate one throwaway
database 0001->0004, build another from the DDL alone, and diff ``information_schema``. This
suite has no fixture that can do that: ``tests/integration/conftest.py`` connects to the LIVE
staging instance at 10.55.0.3 and SKIPS when no DSN is present — there is no template database, no
in-test alembic upgrade, and no local Postgres for Synapse. Building that harness for one
assertion is more machinery than the assertion is worth, so this parses the two artifacts
instead. It cannot catch a difference in TYPE that only Postgres would resolve; it catches the
one that actually happens, which is a column present in one path and absent from the other.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_DDL = _ROOT / "schemas" / "postgres" / "actions.sql"
_VERSIONS = _ROOT / "alembic" / "versions"


def _ddl_columns() -> set[str]:
    """Column names from actions.sql's CREATE TABLE, excluding constraint clauses."""
    body = _DDL.read_text(encoding="utf-8")
    start = body.index("CREATE TABLE synapse.actions (")
    block = body[start : body.index("\n);", start)]
    names: set[str] = set()
    for line in block.splitlines()[1:]:
        stripped = line.strip()
        if not stripped or stripped.startswith("--") or stripped.upper().startswith("CONSTRAINT"):
            continue
        match = re.match(r"^([a-z_]+)\s+[A-Z]", stripped)
        if match:
            names.add(match.group(1))
    return names


def _altered_columns() -> set[str]:
    """Columns any migration ADDs to synapse.actions."""
    added: set[str] = set()
    for path in sorted(_VERSIONS.glob("[0-9]*.py")):
        for match in re.finditer(
            r"ALTER TABLE synapse\.actions ADD COLUMN(?: IF NOT EXISTS)? ([a-z_]+)",
            path.read_text(encoding="utf-8"),
        ):
            added.add(match.group(1))
    return added


def test_the_artifacts_this_test_reads_are_where_it_thinks() -> None:
    """VACUITY GUARD. Both halves are path-based reads; a rename would compare two empty sets and
    pass while checking nothing."""
    assert _DDL.is_file(), f"{_DDL} not found"
    assert list(_VERSIONS.glob("[0-9]*.py")), "no migrations found"
    assert len(_ddl_columns()) >= 15, f"parsed only {sorted(_ddl_columns())}; the regex stopped biting"


def test_every_altered_column_is_also_in_the_ddl() -> None:
    """THE DIRECTION THAT BREAKS A FRESH DEPLOY. A column added only by migration is absent from a
    database built from the DDL, so the two environments diverge and the DDL — which this repo
    calls the source of truth — describes a schema that does not exist."""
    missing = sorted(_altered_columns() - _ddl_columns())
    assert not missing, (
        f"migrations ADD {missing} to synapse.actions and actions.sql does not declare them. "
        "A fresh database would not have them. Add them to the DDL file, as DIS's "
        "0002_identity_mirror_codes does for identity_mirror."
    )


def test_columns_added_by_migration_use_if_not_exists() -> None:
    """THE COROLLARY, and it is not optional once the DDL carries the column.

    A fresh database runs 0001 (which applies the DDL, creating the column) and then the later
    migration. A bare ``ADD COLUMN`` fails there with "column already exists" and breaks the
    chain. ``IF NOT EXISTS`` makes the migration a no-op on the fresh path and the real thing on
    the existing one — which is why DIS's precedent uses it.
    """
    offenders: list[str] = []
    for path in sorted(_VERSIONS.glob("[0-9]*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if "ALTER TABLE synapse.actions ADD COLUMN" in line and "IF NOT EXISTS" not in line:
                offenders.append(f"{path.name}: {line.strip()[:80]}")
    assert not offenders, (
        "these ADD COLUMN statements would fail on a fresh database that already got the column "
        f"from actions.sql: {offenders}"
    )


def test_the_slice_10_observation_columns_are_present_on_both_paths() -> None:
    """Named explicitly, because these are the columns the convention was worked out for."""
    for column in ("days_since_last_sale", "days_of_cover"):
        assert column in _ddl_columns(), f"{column} missing from actions.sql"
        assert column in _altered_columns(), f"{column} missing from the migration chain"
