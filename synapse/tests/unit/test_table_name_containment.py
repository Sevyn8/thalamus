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


def test_the_daily_series_resolver_really_does_name_its_table() -> None:
    """The same non-vacuity guard for the second resolver.

    It matters more here than for current_state: daily_series reaches the table through the
    shared collapse helper, and the helper deliberately names NO table. If the resolver ever
    stopped naming its own, the containment rule would be protecting an empty set again for
    this capability while looking healthy.
    """
    text = (RESOLVERS / "daily_series.py").read_text(encoding="utf-8")
    assert "store_sku_sale_events" in text


def test_the_last_sale_at_resolver_really_does_name_its_table() -> None:
    """The same non-vacuity guard for the fourth capability.

    It reads the SAME table as daily_series, which is why the fourth capability cost no new
    containment surface — but the per-file assertion still matters: if this resolver stopped
    naming its table (say it started importing daily_series's construct), the containment rule
    would be protecting an empty set for it while looking healthy.
    """
    text = (RESOLVERS / "last_sale_at.py").read_text(encoding="utf-8")
    assert "store_sku_sale_events" in text


def test_the_collapse_helper_names_no_table_in_its_code() -> None:
    """The helper is parameterised, so its reusability is a code property worth pinning.

    Prose is exempt: the module explains WHICH tables the D33 key was verified against, and
    it sits under resolvers/ where naming them is allowed. What must not appear is a table
    name inside a `table(...)` construct — that would make the helper sale-events-specific
    and silently un-reusable for change events.
    """
    text = (RESOLVERS / "_collapse.py").read_text(encoding="utf-8")
    code = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("#"))
    body = code.split('"""', 2)[-1]  # everything after the module docstring
    for tbl in CANONICAL_TABLES:
        assert tbl not in body, f"_collapse.py must stay table-agnostic; its code names {tbl!r}"


def test_statement_constructors_are_imported_only_inside_resolvers() -> None:
    """The other half of "only resolvers may reach canonical", for the registry layer.

    import-linter cannot express this one: ``synapse.registry`` MUST import sqlalchemy
    transitively (it binds resolvers that use it), so a forbidden contract on the package
    would either fail or have to allow the thing being guarded. What is checkable is the
    IMPORT FORM: ``from sqlalchemy import ...`` is how select/table/column/text arrive,
    whereas ``from sqlalchemy.ext.asyncio import AsyncEngine`` is a parameter type and
    nothing more. Only resolvers may do the former.
    """
    offenders = [
        str(p.relative_to(SYNAPSE_SRC))
        for p in _python_files()
        if RESOLVERS not in p.parents and "from sqlalchemy import " in p.read_text(encoding="utf-8")
    ]
    assert offenders == [], (
        "statement construction must stay under synapse/resolvers/; these import "
        f"sqlalchemy's constructors directly: {offenders}"
    )


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
