"""D6's table-name half. THIS TEST IS THE MECHANISM, not a belt.

The import-linter contracts in dis/pyproject.toml forbid dis_canonical / dis_rls /
sqlalchemy to synapse.core, and they are real (verified by temporarily adding a
violating import: both contracts break, then pass again once removed). But they
CANNOT express "only resolvers may know a table name", because a table name is a
STRING LITERAL and an import graph cannot see a string.

There is no importable canonical ORM that would turn it into an import either:
dis-canonical is Pydantic-only ("SQL conversion is the consumer's DB layer" — its own
docstring), and the single SQLAlchemy model lives inside the dis-ui-server SERVICE,
which a peer plane must not depend on. Promoting that ORM into a shared lib is the
real fix and is on the ledger as its own slice.

So this grep IS the enforcement for that half. If it is deleted, the rule is gone.
"""

from __future__ import annotations

import pathlib

SYNAPSE_SRC = pathlib.Path(__file__).resolve().parents[2] / "src" / "synapse"
RESOLVERS = SYNAPSE_SRC / "resolvers"

# Canonical tables Synapse could plausibly reach. Extend this list when a resolver
# reaches a new one — the point is that adding a table is a visible edit here.
CANONICAL_TABLES = (
    "store_sku_current_position",
    "store_sku_signal_history",
    "store_sku_sale_events",
    "store_sku_change_events",
)


def _python_files() -> list[pathlib.Path]:
    return sorted(p for p in SYNAPSE_SRC.rglob("*.py"))


def test_canonical_table_names_appear_only_in_resolvers() -> None:
    offenders: list[str] = []
    for path in _python_files():
        if RESOLVERS in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        for tbl in CANONICAL_TABLES:
            if tbl in text:
                offenders.append(f"{path.relative_to(SYNAPSE_SRC)} names {tbl!r}")
    assert offenders == [], (
        f"canonical table names must appear ONLY under synapse/resolvers/ (D6). Offenders: {offenders}"
    )


def test_the_resolver_really_does_name_its_table() -> None:
    """Guard against the test above passing because NOTHING names a table.

    A containment test over an empty set is vacuously true. This asserts the rule has
    something to contain — if the resolver stops naming the table (say it grows an ORM
    import instead), this fails and the containment test needs rethinking rather than
    silently protecting nothing.
    """
    text = (RESOLVERS / "current_state.py").read_text(encoding="utf-8")
    assert "store_sku_current_position" in text


def test_synapse_never_builds_a_write_statement() -> None:
    """D7: Synapse is read-only on canonical. No INSERT/UPDATE/DELETE construction."""
    forbidden = ("sqlalchemy import insert", "sqlalchemy import update", "sqlalchemy import delete")
    offenders = [
        f"{p.relative_to(SYNAPSE_SRC)}: {frag}"
        for p in _python_files()
        for frag in forbidden
        if frag in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"Synapse must never write a DIS table (D7). Offenders: {offenders}"
