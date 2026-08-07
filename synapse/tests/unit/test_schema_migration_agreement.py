"""Every synapse table must look the same whether it was built from DDL or reached by migrations.

WHY THIS EXISTS. ``schemas/postgres/*.sql`` are the source of truth and the migrations apply them
VERBATIM, so a FRESH database gets its columns from the DDL files. An EXISTING database gets later
columns from ``ALTER`` statements in migrations. Those are two paths to one schema and nothing
makes them agree — the DIS precedent (``0002_identity_mirror_codes``) keeps them in step by hand:
it ALTERs the table and also carries the columns in ``identity_mirror/tenants.sql``/``stores.sql``.

That hand-agreement is exactly the kind that drifts silently, and the drift is invisible until a
fresh deploy behaves differently from staging. So the two are compared here.

IT COVERED ONLY synapse.actions UNTIL SLICE 5b, and the gap was real rather than theoretical: the
constant was a single ``_DDL = .../actions.sql``, so migration 0005 adding ``refusals`` to
``synapse.run`` would have been checked against nothing at all. A guard whose scope is narrower
than its name is worse than an absent one, because the green tick is read as coverage. All three
tables are now enumerated in ``_TABLES``, and a fourth table added without a row there fails
``test_every_synapse_table_is_covered`` rather than being silently unguarded.

WHY IT IS A FILE COMPARISON AND NOT A DATABASE ONE. The obvious test is to migrate one throwaway
database 0001->head, build another from the DDL alone, and diff ``information_schema``. The
disposable-database harness added for the live write tests could now do that, but it runs only in
the integration suite and only when armed with a DSN — so the check would be absent exactly when
somebody edits a migration on a laptop. This parses the two artifacts instead and runs on every
``make test``. It cannot catch a difference in TYPE that only Postgres would resolve; it catches
the one that actually happens, which is a column present in one path and absent from the other.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_VERSIONS = _ROOT / "alembic" / "versions"
_SCHEMAS = _ROOT / "schemas" / "postgres"

# (table, ddl file, minimum column count for the vacuity guard). The minimum is a floor well
# under the real count, there to prove the regex still bites rather than to pin the schema.
_TABLES: tuple[tuple[str, str, int], ...] = (
    ("actions", "actions.sql", 15),
    ("run", "run.sql", 10),
    ("provision", "provision.sql", 6),
    ("action_events", "action_events.sql", 8),
    ("quarantined_tenants", "quarantined_tenants.sql", 5),
)


def _ddl_path(filename: str) -> Path:
    return _SCHEMAS / filename


def _ddl_columns(table: str, filename: str) -> set[str]:
    """Column names from one DDL file's CREATE TABLE, excluding constraint clauses.

    Tolerates both ``CREATE TABLE synapse.x (`` and ``CREATE TABLE IF NOT EXISTS synapse.x (`` —
    this repo uses both forms across the three files, and hard-coding one silently returned an
    empty set for the other two.
    """
    body = _ddl_path(filename).read_text(encoding="utf-8")
    opening = re.search(rf"^CREATE TABLE (?:IF NOT EXISTS )?synapse\.{table} \($", body, re.M)
    if opening is None:
        return set()
    block = body[opening.end() : body.index("\n);", opening.end())]
    names: set[str] = set()
    for line in block.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--") or stripped.upper().startswith("CONSTRAINT"):
            continue
        match = re.match(r"^([a-z_]+)\s+[A-Z]", stripped)
        if match:
            names.add(match.group(1))
    return names


def _altered_columns(table: str) -> set[str]:
    """Columns any migration ADDs to one synapse table."""
    added: set[str] = set()
    for path in sorted(_VERSIONS.glob("[0-9]*.py")):
        for match in re.finditer(
            rf"ALTER TABLE synapse\.{table} ADD COLUMN(?: IF NOT EXISTS)? ([a-z_]+)",
            path.read_text(encoding="utf-8"),
        ):
            added.add(match.group(1))
    return added


# ---------------------------------------------------------------------------
# Vacuity guards: both halves are path- and regex-based, so both can go quiet
# ---------------------------------------------------------------------------


def test_every_synapse_table_is_covered() -> None:
    """THE GAP THIS TEST SHIPPED WITH. Until slice 5b it read actions.sql alone, so `run` and
    `provision` were unguarded while the file's name and docstring implied otherwise. A new DDL
    file must be added to _TABLES or this fails."""
    on_disk = {path.name for path in _SCHEMAS.glob("*.sql")}
    covered = {filename for _, filename, _ in _TABLES}
    assert on_disk == covered, (
        f"schemas/postgres holds {sorted(on_disk)} but this test covers {sorted(covered)}. "
        "An uncovered DDL file drifts from its migrations with nothing to say so."
    )


@pytest.mark.parametrize(("table", "filename", "minimum"), _TABLES)
def test_the_artifacts_this_test_reads_are_where_it_thinks(table: str, filename: str, minimum: int) -> None:
    """A rename, or a CREATE TABLE form the regex does not match, would compare two empty sets and
    pass while checking nothing."""
    assert _ddl_path(filename).is_file(), f"{_ddl_path(filename)} not found"
    assert list(_VERSIONS.glob("[0-9]*.py")), "no migrations found"
    parsed = _ddl_columns(table, filename)
    assert len(parsed) >= minimum, (
        f"parsed only {sorted(parsed)} from {filename}; the regex stopped biting on synapse.{table}"
    )


# ---------------------------------------------------------------------------
# The agreement itself
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("table", "filename", "minimum"), _TABLES)
def test_every_altered_column_is_also_in_the_ddl(table: str, filename: str, minimum: int) -> None:
    """THE DIRECTION THAT BREAKS A FRESH DEPLOY. A column added only by migration is absent from a
    database built from the DDL, so the two environments diverge and the DDL — which this repo
    calls the source of truth — describes a schema that does not exist."""
    missing = sorted(_altered_columns(table) - _ddl_columns(table, filename))
    assert not missing, (
        f"migrations ADD {missing} to synapse.{table} and {filename} does not declare them. "
        "A fresh database would not have them. Add them to the DDL file, as DIS's "
        "0002_identity_mirror_codes does for identity_mirror."
    )


@pytest.mark.parametrize(("table", "filename", "minimum"), _TABLES)
def test_columns_added_by_migration_use_if_not_exists(table: str, filename: str, minimum: int) -> None:
    """THE COROLLARY, and it is not optional once the DDL carries the column.

    A fresh database runs the bootstrap migration (which applies the DDL, creating the column) and
    then the later migration. A bare ``ADD COLUMN`` fails there with "column already exists" and
    breaks the chain. ``IF NOT EXISTS`` makes the migration a no-op on the fresh path and the real
    thing on the existing one — which is why DIS's precedent uses it.
    """
    offenders: list[str] = []
    for path in sorted(_VERSIONS.glob("[0-9]*.py")):
        for line in path.read_text(encoding="utf-8").splitlines():
            if f"ALTER TABLE synapse.{table} ADD COLUMN" in line and "IF NOT EXISTS" not in line:
                offenders.append(f"{path.name}: {line.strip()[:80]}")
    assert not offenders, (
        f"these ADD COLUMN statements would fail on a fresh database that already got the column "
        f"from {filename}: {offenders}"
    )


# ---------------------------------------------------------------------------
# The columns each convention was worked out for, named explicitly
# ---------------------------------------------------------------------------


def test_the_slice_10_observation_columns_are_present_on_both_paths() -> None:
    for column in ("days_since_last_sale", "days_of_cover"):
        assert column in _ddl_columns("actions", "actions.sql"), f"{column} missing from actions.sql"
        assert column in _altered_columns("actions"), f"{column} missing from the migration chain"


def test_the_slice_5b_refusal_column_is_present_on_both_paths() -> None:
    """The column this coverage gap was found by. Migration 0005 adds it to synapse.run; run.sql
    must declare it or a fresh database has a run table the orchestrator cannot write."""
    assert "refusals" in _ddl_columns("run", "run.sql"), "refusals missing from run.sql"
    assert "refusals" in _altered_columns("run"), "refusals missing from the migration chain"
