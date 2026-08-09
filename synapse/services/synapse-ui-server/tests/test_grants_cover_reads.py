"""Every object reads.py names must be readable by synapse_reader. Checked from the repository.

===============================================================================================
THE INTER-ARTIFACT PAIR ENUMERATION FOR 8a
===============================================================================================
Five deployment failures in one slice, every one knowable from the repository, none needing a
running system. They were not caught because every technique in this project is INTRA-artifact:
does this guard fire, does it cover its claim, does the image contain what I put in it. Each
artifact WAS correct. Every failure was a JOIN — a thing against its counterpart — and a join is
nobody's file. Writing both sides does not force the comparison: you write A thinking about A,
then B thinking about B.

A checklist that gains one item per incident is permanently one incident behind. So this is the
enumeration written OUT of incident order, and it lives here — attached to the checker — because
A CHECKER THAT DOES NOT DOCUMENT WHAT IT CANNOT COVER IS THE SAME DEFECT IT EXISTS TO PREVENT.
This file checks pair #6. The other twenty are listed so that "the grant check passes" is never
mistaken for "the pairs agree".

  KEY   [static]  both sides in the repo — a checker is possible
        [live]    one side exists only in a running system
        [check]   a static check EXISTS today          [none] no check yet

   1. container CMD              <-> symbol the code exports          [static] [check]
        Dockerfile resolves $ASGI_TARGET through uvicorn's own importer and calls it.
   2. deployed image             <-> committed code                   [live]
   3. runtime env provided       <-> env read, AND WHEN it is read    [static] [none]
        The "when" half is load-bearing and was its own failure: a module-scope read is bound at
        import, which for a prerendered Next.js page means BUILD time.
   4. callee ingress             <-> caller egress                    [static] [none]
        INTERNAL_ONLY is satisfiable only if the caller routes egress through a VPC.
   5. header client sends        <-> header server verifies           [static] [none]
   6. query schema refs          <-> role grants                      [static] [check]  <-- HERE
   7. client paths               <-> server routes (+ METHOD, required query params)
                                                                      [static] [none]
   8. response shapes            <-> client types                     [static] [none]
   9. query columns              <-> actual DDL                       [static] [none]
  10. RLS policy                 <-> the session's GUCs               [static] [none]
        Not "is PLATFORM mentioned" — is the disjunct INSIDE the USING clause.
  11. secret referenced by tf    <-> secret that exists               [live]
  12. env var name on producer   <-> name on consumer                 [static] [none]
        Here a THREE-way: SYNAPSE_BFF_URL is also the ID-token audience.
  13. service account roles      <-> the APIs the code calls          [static] [none]
  14. module written             <-> module instantiated in an env    [static] [none]
  15. alembic head in repo       <-> migration state in the DB        [live]
  16. Dockerfile COPY set        <-> the package's import closure     [static] [check]
  17. declarations in code       <-> rows in data                     [live]
  18. job/scheduler args         <-> the entrypoint's arg parser      [static] [none]
  19. .dockerignore              <-> files the build needs            [static] [none]
  20. a tf variable's DESCRIPTION<-> its VALUE                        [static] [none]
  21. a claim in artifact A ABOUT artifact B's config <-> B's config  [static] [none]
        Surfaced BY the audit: relaxing this service's ingress falsified two comments elsewhere
        in the same session, before the change was even applied.

  22. A FAILURE DEEP IN THE STACK IS POSITIVE EVIDENCE FOR EVERY PAIR UPSTREAM OF IT.
        Not a pair — the rule for reading one. A 500 from a handler proves the image exists and
        pulled (#2), the secret reference resolved (#11), the SA could read it (#13), the module
        was instantiated (#14) and the COPY set was complete (#16) — a revision missing any of
        those never starts and never reaches a handler. Reading a 500 as only bad news discards
        five verified pairs. THE DEPTH OF A FAILURE IS A MEASUREMENT.

  WHERE INSTANCES 6+ WILL COME FROM: the [live] rows. For those the answer is not a static check,
  it is one real call — see the standing rule, exercise the path once in the slice that makes it.

===============================================================================================
WHAT THIS FILE CHECKS, AND ONE THING IT LEARNED THE HARD WAY
===============================================================================================
It parses reads.py for every schema-qualified object and confirms synapse_reader is granted
USAGE on the schema and SELECT on the table.

IT MUST READ THE MIGRATIONS, NOT ONLY infra/db-setup/sql/. Auditing this by hand, I read sql/04's
REVOKE-ALL-then-GRANT-actions and concluded provision and run were ungranted. They are granted —
by alembic 0003, lines 76-77. A checker scoped to the hand-run files would have reported two
false positives with total confidence. GRANTS IN THIS PROJECT COME FROM TWO PLACES AND NEITHER IS
COMPLETE ALONE.

IT ERRS TOWARD REPORTING. The SQL parsing is deliberately crude. A grant it cannot prove is a
grant it reports. False positives cost a line of explanation; false negatives are what shipped.
"""

from __future__ import annotations

import re
from pathlib import Path

_HERE = Path(__file__).resolve()
_REPO_ROOT = _HERE.parents[4]
_READS = _HERE.parents[1] / "src" / "synapse_ui_server" / "reads.py"
_SQL_DIR = _REPO_ROOT / "infra" / "db-setup" / "sql"
_MIGRATIONS = sorted((_REPO_ROOT / "synapse" / "alembic" / "versions").glob("[0-9]*.py"))

ROLE = "synapse_reader"


# ---------------------------------------------------------------------------
# What the code needs
# ---------------------------------------------------------------------------


def required_objects() -> set[tuple[str, str]]:
    """Every ``schema.table`` reached by a FROM or JOIN in reads.py's SQL.

    READS THE COMPILED STATEMENTS, NOT THE SOURCE TEXT, and B2a is why. This used to regex the
    file for ``text(\"\"\"...\"\"\")`` literals. When the fleet and tenant statements became
    f-strings so they could interpolate the ONE shared lifecycle construct, the regex stopped
    matching them: it required a ``\"\"\"`` immediately after ``text(`` and an ``f`` now sat
    between. The parser silently fell from nine objects to four, and the only thing that
    noticed was the vacuity guard below.

    Source-scraping could not have been repaired by widening the pattern either. The shared
    constructs are interpolated, so ``_FLEET``'s source contains ``{_OPEN_ALERTS_BY_TENANT}``
    and never the words ``synapse.actions_analytical``: the table this slice moved the open
    count ONTO would have stayed invisible to the grant check. Compiled statements carry the
    resolved SQL, so a construct is checked wherever it is used rather than where it is
    written.

    SQL line comments are stripped first. The statements now carry prose about which tables a
    deleted copy used to read, and a comment must not manufacture a grant requirement -- the
    same reason the old version scoped itself to literals.
    """
    from sqlalchemy.sql.elements import TextClause
    from synapse_ui_server import reads as reads_module

    found: set[tuple[str, str]] = set()
    for name in dir(reads_module):
        statement = getattr(reads_module, name)
        if not isinstance(statement, TextClause):
            continue
        body = re.sub(r"--[^\n]*", "", str(statement))
        for schema, table in re.findall(r"\b(?:FROM|JOIN)\s+([a-z_]+)\.([a-z_]+)", body, re.I):
            found.add((schema.lower(), table.lower()))
    return found


# ---------------------------------------------------------------------------
# What the database grants
# ---------------------------------------------------------------------------


def _resolve_constants(source: str) -> str:
    """Substitute a migration's module-level string constants into its f-strings.

    Migrations write ``op.execute(f"GRANT SELECT ON synapse.run TO {_READER}")``. Without
    resolving ``_READER`` the grant is invisible — which is exactly the false negative that makes
    a checker worse than no checker, because it is trusted.
    """
    for name, value in re.findall(r'^(_[A-Z]+|SCHEMA)\s*=\s*"([^"]+)"', source, re.M):
        source = source.replace("{" + name + "}", value)
    # `for role in (_WRITER, _READER):` with `{role}` in the body — expand to one line per role.
    loop = re.search(r"for role in \(([^)]+)\):", source)
    if loop:
        roles = [r.strip() for r in loop.group(1).split(",")]
        expanded: list[str] = []
        for line in source.splitlines():
            if "{role}" in line:
                expanded.extend(line.replace("{role}", r) for r in roles)
            else:
                expanded.append(line)
        source = "\n".join(expanded)
    return source


def _grant_sources() -> dict[str, str]:
    """Every file that can change this role's privileges, hand-run and migrated alike.

    SQL LINE COMMENTS ARE STRIPPED FROM THE HAND-RUN FILES, and slice 5e is why. These files
    document each other at length: sql/05's header explains the sql/04 pairing defect by QUOTING
    sql/04's ``REVOKE ALL ON ALL TABLES IN SCHEMA synapse FROM synapse_reader``, and the
    hazard regex below matched the quotation. It reported sql/05 as stripping six tables it does
    not mention, in a paragraph whose entire subject is not doing that.

    A COMMENT CANNOT REVOKE ANYTHING, so reading one as a revoke is the same error as reading one
    as a grant, which ``required_objects`` already strips comments to avoid. This is that fix
    applied to the other half of the file.

    THE CHECKER STILL ERRS TOWARD REPORTING. This removes a class of FALSE POSITIVE that comes
    from prose, not a class of true finding: nothing that acts on the database is inside a
    ``--``.
    """
    sources = {
        p.name: re.sub(r"--[^\n]*", "", p.read_text(encoding="utf-8")) for p in sorted(_SQL_DIR.glob("*.sql"))
    }
    for path in _MIGRATIONS:
        sources[f"alembic/{path.name}"] = _resolve_constants(path.read_text(encoding="utf-8"))
    return sources


def granted_schemas() -> set[str]:
    out: set[str] = set()
    for text in _grant_sources().values():
        for schema in re.findall(
            rf'GRANT\s+[\w,\s]*USAGE[\w,\s]*\s+ON\s+SCHEMA\s+"?([a-z_]+)"?\s+TO\s+[^;\n"]*{ROLE}',
            text,
            re.I,
        ):
            out.add(schema.lower())
    return out


def granted_tables() -> set[tuple[str, str]]:
    """Explicit ``GRANT SELECT ON schema.table TO synapse_reader``, plus schemas covered by
    ``ALTER DEFAULT PRIVILEGES ... GRANT SELECT ON TABLES``, which is how a table created by a
    later migration arrives readable without being named."""
    out: set[tuple[str, str]] = set()
    default_schemas: set[str] = set()
    for text in _grant_sources().values():
        for privs, schema, table, grantees in re.findall(
            r"GRANT\s+([A-Z,\s]+?)\s+ON\s+(?:TABLE\s+)?\"?([a-z_]+)\"?\.\"?([a-z_]+)\"?\s+TO\s+([^;\n]+)",
            text,
            re.I,
        ):
            if ROLE in grantees and re.search(r"\bSELECT\b|\bALL\b", privs, re.I):
                out.add((schema.lower(), table.lower()))
        for schema in re.findall(
            rf'ALTER\s+DEFAULT\s+PRIVILEGES\s+IN\s+SCHEMA\s+"?([a-z_]+)"?\s+GRANT\s+[A-Z,\s]*SELECT[A-Z,\s]*\s+ON\s+TABLES\s+TO\s+[^;\n"]*{ROLE}',
            text,
            re.I,
        ):
            default_schemas.add(schema.lower())
    for schema in default_schemas:
        out.update({(s, t) for s, t in required_objects() if s == schema})
    return out


# ---------------------------------------------------------------------------
# The checks
# ---------------------------------------------------------------------------


def test_the_parser_found_something_to_check() -> None:
    """VACUITY GUARD. Every assertion below is over a parsed set; a regex that silently stops
    matching turns this whole file green while checking nothing."""
    assert _READS.is_file(), f"{_READS} not found"
    assert _SQL_DIR.is_dir(), f"{_SQL_DIR} not found"
    assert _MIGRATIONS, "no synapse migrations found — grants live there too, see the header"
    required = required_objects()
    assert len(required) >= 5, f"parsed only {required} from reads.py; the regex has stopped biting"
    assert granted_tables(), "parsed zero table grants from any source; the regex has stopped biting"


def test_every_object_reads_py_names_is_granted_to_synapse_reader() -> None:
    """THE CHECK. Names the offenders, both halves separately, because USAGE and SELECT fail
    differently and fixing one without the other still returns permission denied."""
    required = required_objects()
    schemas_ok = granted_schemas()
    tables_ok = granted_tables()

    missing_usage = sorted({s for s, _ in required} - schemas_ok)
    missing_select = sorted(f"{s}.{t}" for s, t in required if (s, t) not in tables_ok)

    problems: list[str] = []
    if missing_usage:
        problems.append(f"no USAGE on schema(s): {missing_usage}")
    if missing_select:
        problems.append(f"no SELECT on table(s): {missing_select}")

    assert not problems, (
        f"reads.py queries objects {ROLE} cannot read: {'; '.join(problems)}. "
        "Every query naming one of these fails with 'permission denied' (SQLSTATE 42501) — a 500 "
        "from the BFF, not a silent zero, because identity_mirror has no RLS. Grant in "
        "infra/db-setup/sql/03_synapse_reader_grant.sql, which is the file that defines what this "
        "role reads and is idempotent by design."
    )


def test_no_hand_run_file_revokes_what_a_migration_granted() -> None:
    """F9. A blanket REVOKE in a re-runnable file silently undoes a migration's grants.

    ``sql/04`` predates migration 0003. It does ``REVOKE ALL ON ALL TABLES IN SCHEMA synapse FROM
    synapse_reader`` and then grants back only ``synapse.actions``. Re-running it today strips
    SELECT on provision and run — breaking all three database-backed console routes — and its
    ``REVOKE UPDATE ... ON ALL TABLES FROM synapse_writer`` also strips the UPDATE that 0003 gave
    the writer on synapse.run, which is how the orchestrator records a finish.

    Both files are individually correct. The pair is not. Nothing about running one tells you it
    invalidates the other, which is why this is a test and not a comment in either.
    """
    migration_granted = {
        (s.lower(), t.lower())
        for path in _MIGRATIONS
        for privs, s, t, grantees in re.findall(
            r"GRANT\s+([A-Z,\s]+?)\s+ON\s+\"?([a-z_]+)\"?\.\"?([a-z_]+)\"?\s+TO\s+([^\"'\n]+)",
            _resolve_constants(path.read_text(encoding="utf-8")),
            re.I,
        )
        if ROLE in grantees and re.search(r"\bSELECT\b", privs, re.I)
    }

    hazards: list[str] = []
    for name, text in _grant_sources().items():
        if name.startswith("alembic/"):
            continue
        for schema in re.findall(
            rf"REVOKE\s+ALL\s+ON\s+ALL\s+TABLES\s+IN\s+SCHEMA\s+([a-z_]+)\s+FROM\s+[^;\n]*{ROLE}",
            text,
            re.I,
        ):
            stripped = sorted(
                f"{s}.{t}"
                for s, t in migration_granted
                if s == schema.lower() and f"{s}.{t}" not in _explicit_regrants(text)
            )
            if stripped:
                hazards.append(f"{name} revokes all on schema {schema}, stripping {stripped}")

    assert not hazards, (
        "a re-runnable hand-run file would revoke grants a migration made: "
        + "; ".join(hazards)
        + ". Fix by re-granting in that file, or by narrowing the REVOKE. Until then, DO NOT "
        "re-run it: the console and the orchestrator both depend on those grants."
    )


def _explicit_regrants(text: str) -> set[str]:
    return {
        f"{s.lower()}.{t.lower()}"
        for privs, s, t, grantees in re.findall(
            r"GRANT\s+([A-Z,\s]+?)\s+ON\s+\"?([a-z_]+)\"?\.\"?([a-z_]+)\"?\s+TO\s+([^;\n]+)",
            text,
            re.I,
        )
        if ROLE in grantees and re.search(r"\bSELECT\b|\bALL\b", privs, re.I)
    }
