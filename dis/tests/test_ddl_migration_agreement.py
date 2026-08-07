"""Every column a migration ADDs must also be declared in its table's DDL file.

WHY THIS EXISTS. DIS's tables are created by applying ``schemas/postgres/**.sql`` VERBATIM —
0001 applies sixteen of the nineteen files, 0013 and 0016 one each. Later migrations then ALTER
those tables. That makes two paths to one schema:

    FRESH     0001 applies the DDL file (which already carries the column) and the later
              migration's gated ADD COLUMN is a no-op.
    EXISTING  the table was built from an older DDL file and the ALTER is what adds the column.

Nothing makes the two agree. If a migration ALTERs and its DDL file is not updated, both paths
still work — until they disagree about type or nullability, and then a fresh deploy differs from
production in a way no test looks at. That is the drift this file refuses.

IT RUNS WITHOUT A DATABASE, WHICH IS THE POINT. tests/integration/test_schema_agreement.py proves
the two paths CONVERGE by executing the chain, and it is the stronger check — but it needs the
stack, so it is absent exactly when somebody is writing 0020 on a laptop. This one fires there.

THE EXTRACTOR MUST BE COMPLETE OR IT IS WORSE THAN NOTHING. Six ADD COLUMNs in this chain are
plain literals; four are f-strings over module constants, one of them with BOTH the table and the
column interpolated (0003:146). A regex that read only the literals would report six of ten and
pass — coverage by appearance. So the resolver expands module attributes, and
``test_every_add_column_in_the_chain_was_resolved`` fails if any occurrence was not accounted
for, naming the file and line.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_VERSIONS = _ROOT / "alembic" / "versions"
_SCHEMAS = _ROOT / "schemas" / "postgres"

# Any ADD COLUMN, however the statement was built. Used both to resolve pairs and to count what
# the resolver must account for.
_ADD_COLUMN = re.compile(r"ADD COLUMN(?:\s+IF\s+NOT\s+EXISTS)?\s+(\S+)", re.I)
_ALTER_TABLE = re.compile(r"ALTER TABLE\s+(\S+)", re.I)


def _revisions() -> list[Path]:
    return sorted(_VERSIONS.glob("[0-9]*.py"))


def _module_constants(source: str) -> dict[str, object]:
    """Module-level assignments, evaluated statically and ELEMENT-WISE for tuples.

    Element-wise because ``literal_eval`` on the whole value fails when a tuple mixes literals
    with name references — 0003's ``_EVENT_TABLES`` pairs a table name with a comment constant,
    and an all-or-nothing eval dropped the table names this test needs. Unresolvable elements
    become None and are skipped later rather than guessed at.
    """
    constants: dict[str, object] = {}
    for node in ast.parse(source).body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        target = node.targets[0]
        if not isinstance(target, ast.Name):
            continue
        constants[target.id] = _literal(node.value)
    return constants


def _literal(node: ast.AST) -> object:
    """Best-effort literal, recursing into tuples so one unresolvable element does not lose the
    rest. Non-literals (``os.environ.get(...)`` in the target guards) become None."""
    if isinstance(node, ast.Tuple | ast.List):
        return tuple(_literal(e) for e in node.elts)
    try:
        return ast.literal_eval(node)
    except (ValueError, TypeError, SyntaxError):
        return None


def _loop_sources(source: str) -> dict[str, list[object]]:
    """Loop variable -> the values it takes, for ``for a, b in _CONST:`` over a literal tuple.

    Generic rather than per-migration: 0003 and 0019 both iterate a module-level tuple of tuples,
    and hard-coding either one here would be a second source of truth that rots the next time a
    migration is written in the same shape.
    """
    constants = _module_constants(source)
    bound: dict[str, list[object]] = {}
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.For) or not isinstance(node.iter, ast.Name):
            continue
        values = constants.get(node.iter.id)
        if not isinstance(values, tuple | list):
            continue
        targets = (
            [node.target] if isinstance(node.target, ast.Name) else list(getattr(node.target, "elts", []))
        )
        for position, element in enumerate(targets):
            if not isinstance(element, ast.Name):
                continue
            column: list[object] = []
            for row in values:
                if isinstance(row, tuple | list):
                    if position < len(row):
                        column.append(row[position])
                elif position == 0:
                    column.append(row)
            bound.setdefault(element.id, []).extend(column)
    return bound


def _candidates(name: str, source: str) -> list[str]:
    """Every value a ``{name}`` placeholder could take: a module constant, or a loop variable."""
    constants = _module_constants(source)
    value = constants.get(name)
    if isinstance(value, str):
        return [value]
    bound = _loop_sources(source).get(name, [])
    return [str(v) for v in bound if isinstance(v, str)]


def _first_token(ddl: str) -> str:
    """``row_hash VARCHAR(64) COLLATE "C"`` -> ``row_hash``. A column DDL fragment leads with the
    column name, which is the only part this test needs."""
    return ddl.strip().split()[0]


def _resolve(fragment: str, source: str) -> list[str]:
    """Expand ``{placeholder}`` against the module, or return the literal unchanged."""
    placeholder = re.fullmatch(r"\{([A-Za-z_][A-Za-z0-9_]*)\}", fragment.strip())
    if placeholder is None:
        return [fragment]
    return _candidates(placeholder.group(1), source)


def _render(node: ast.AST) -> str | None:
    """A string constant or an f-string rendered with ``{name}`` left in place.

    F-STRINGS MATTER HERE: four of the chain's ADD COLUMNs are built that way, one with both the
    table and the column interpolated. Rendering the placeholder rather than dropping it is what
    lets _resolve expand it from the module.
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        out = []
        for part in node.values:
            if isinstance(part, ast.Constant) and isinstance(part.value, str):
                out.append(part.value)
            elif isinstance(part, ast.FormattedValue) and isinstance(part.value, ast.Name):
                out.append("{" + part.value.id + "}")
            else:
                out.append("{?}")
        return "".join(out)
    return None


def _sql_strings(source: str) -> list[str]:
    """Every string in the module that is NOT a docstring.

    PROSE IS NOT A STATEMENT, and conflating them is why the first version of this test reported
    six false positives: six migrations DISCUSS "ADD COLUMN" in their docstrings to explain how
    they gate it. A docstring is a bare expression statement; SQL is an argument to a call or a
    module constant. The AST separates them cleanly, where a line scan cannot.
    """
    tree = ast.parse(source)
    docstrings = {
        id(node.body[0].value)
        for node in ast.walk(tree)
        if isinstance(node, ast.Module | ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef)
        and node.body
        and isinstance(node.body[0], ast.Expr)
        and isinstance(node.body[0].value, ast.Constant)
    }
    # AN F-STRING'S FRAGMENTS ARE ALSO NODES. ast.walk yields the JoinedStr AND each Constant
    # inside it, so 0003's `f"ALTER TABLE {t} ADD COLUMN IF NOT EXISTS {c} NOT NULL"` produced
    # both the rendered statement and the bare fragment " ADD COLUMN IF NOT EXISTS " — which
    # matched as a column named "IF". Owned fragments are skipped; the rendered whole is kept.
    owned = {id(part) for node in ast.walk(tree) if isinstance(node, ast.JoinedStr) for part in node.values}
    found: list[str] = []
    for node in ast.walk(tree):
        if id(node) in docstrings or id(node) in owned:
            continue
        rendered = _render(node)
        if rendered is not None:
            found.append(rendered)
    return found


def added_columns() -> tuple[set[tuple[str, str]], list[str]]:
    """(schema.table, column) pairs the chain ADDs, and any occurrence it could not resolve.

    The table is taken from the SAME string as the ADD COLUMN, or from the most recent ALTER
    TABLE string in the module when the statement was split across two. Same-string first: the
    first version looked only at PRECEDING lines and paired 0002's `store_code` with
    `identity_mirror.tenants` — the table from the ALTER three lines above — which is a false
    drift report against a chain that has none.
    """
    pairs: set[tuple[str, str]] = set()
    unresolved: list[str] = []
    for path in _revisions():
        source = path.read_text(encoding="utf-8")
        pending_table: str | None = None
        for text in _sql_strings(source):
            table_match = _ALTER_TABLE.search(text)
            if table_match is not None:
                pending_table = table_match.group(1).strip("\"';")
            add_match = _ADD_COLUMN.search(text)
            if add_match is None:
                continue
            if pending_table is None:
                unresolved.append(f"{path.name}: {text[:70]!r} (no ALTER TABLE seen)")
                continue
            tables = _resolve(pending_table, source)
            columns = [_first_token(c) for c in _resolve(add_match.group(1).strip("\"';"), source)]
            if not tables or not columns:
                unresolved.append(f"{path.name}: {text[:70]!r}")
                continue
            for table in tables:
                for column in columns:
                    pairs.add((table.strip("\"';"), column.strip("\"';,")))
    return pairs, unresolved


def _ddl_path(qualified: str) -> Path:
    schema, _, table = qualified.partition(".")
    return _SCHEMAS / schema / f"{table}.sql"


# ---------------------------------------------------------------------------
# Vacuity guards: this test is two regexes over a directory, so both can go quiet
# ---------------------------------------------------------------------------


def test_the_artifacts_this_test_reads_are_where_it_thinks() -> None:
    assert len(_revisions()) >= 19, f"found {len(_revisions())} revisions; the glob stopped biting"
    assert len(list(_SCHEMAS.rglob("*.sql"))) >= 19, "the DDL tree moved"


def test_the_chain_really_does_add_columns() -> None:
    """If the extractor returned nothing, every agreement assertion below would pass trivially —
    the 0-rows-prove-nothing failure this project has paid for elsewhere."""
    pairs, _ = added_columns()
    assert len(pairs) >= 8, f"resolved only {sorted(pairs)}; the extractor stopped biting"


def test_every_add_column_in_the_chain_was_resolved() -> None:
    """THE COMPLETENESS ASSERTION, and it is what makes this guard honest.

    Four of the chain's ADD COLUMNs are built from f-strings over module constants — 0003:146
    interpolates BOTH the table and the column. A resolver that silently skipped those would
    report a subset and pass, which reads as coverage. If a future migration writes its ALTER in
    a shape the resolver cannot expand, this fails and names it rather than quietly ignoring it.
    """
    _, unresolved = added_columns()
    assert unresolved == [], (
        "these ADD COLUMN statements could not be resolved to a (table, column) pair, so they "
        f"were NOT checked against any DDL file: {unresolved}. Extend _resolve, or write the "
        "ALTER with a literal table and column."
    )


# ---------------------------------------------------------------------------
# The agreement itself
# ---------------------------------------------------------------------------


def test_every_added_column_has_a_ddl_file() -> None:
    """A migration ALTERing a table with no DDL file means the table is migration-only, which is
    a different (and currently non-existent) pattern in this repo. Named so it is a decision."""
    pairs, _ = added_columns()
    missing = sorted({t for t, _ in pairs if not _ddl_path(t).is_file()})
    assert missing == [], f"ALTERed tables with no schemas/postgres file: {missing}"


def test_every_added_column_is_declared_in_its_ddl_file() -> None:
    """THE 0020 TRIPWIRE. A column added only by migration is absent from a database built from
    the DDL files, so a fresh deploy and production diverge — and the DDL, which this repo calls
    the source of truth, describes a schema that does not exist.
    """
    pairs, _ = added_columns()
    offenders = sorted(
        f"{table}.{column}"
        for table, column in pairs
        if _ddl_path(table).is_file()
        and not re.search(
            rf"^\s*{re.escape(column)}\s+\S", _ddl_path(table).read_text(encoding="utf-8"), re.M
        )
    )
    assert offenders == [], (
        f"migrations ADD these columns and their DDL files do not declare them: {offenders}. "
        "A fresh database would not have them. Add them to schemas/postgres/<schema>/<table>.sql "
        "in the same commit, as 0002_identity_mirror_codes does for identity_mirror."
    )


def test_columns_added_by_migration_are_gated_for_the_fresh_path() -> None:
    """THE COROLLARY, and it is not optional once the DDL file carries the column.

    A fresh database runs 0001 (which applies the DDL, creating the column) and then the later
    migration. An ungated ``ADD COLUMN`` fails there with "column already exists" and breaks the
    chain. Either ``IF NOT EXISTS`` or an explicit existence gate makes the migration a no-op on
    the fresh path and the real thing on the existing one.

    BOTH FORMS ARE ACCEPTED because this chain uses both: 0006/0010/0017 gate by querying
    information_schema first, which IF NOT EXISTS cannot express when a COMMENT or a CHECK swap
    has to be gated with it.
    """
    offenders: list[str] = []
    for path in _revisions():
        source = path.read_text(encoding="utf-8")
        gated_by_query = "information_schema.columns" in source
        for line_no, line in enumerate(source.splitlines(), start=1):
            if not _ADD_COLUMN.search(line) or line.strip().startswith("#"):
                continue
            if re.search(r"IF\s+NOT\s+EXISTS", line, re.I) or gated_by_query:
                continue
            offenders.append(f"{path.name}:{line_no} {line.strip()[:70]}")
    assert offenders == [], (
        "these ADD COLUMN statements are neither IF NOT EXISTS nor guarded by an "
        f"information_schema existence check, so they fail on a fresh database: {offenders}"
    )
