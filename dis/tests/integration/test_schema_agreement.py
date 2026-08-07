"""The WHOLE schema, fresh chain vs migrated reference. One test, four object classes.

WHAT THIS ADDS THAT THE PER-MIGRATION TESTS DO NOT. DIS already runs `fresh == migrated` per
revision — fifteen files, test_migration_0002.py through 0018.py, a discipline established at
0011/0012. But each compares ONLY ITS OWN migration's objects: test_migration_0014.py:120-137
diffs exactly two named columns. Nothing looks at the schema as a whole, so drift in any object
no single migration test named is invisible, and four revisions (0001, 0006, 0016, 0019) have no
test file at all — 0016 creates a whole table from a DDL file and 0019 is the most recent change
in the chain.

This sweeps all eight DIS schemas: columns, indexes, constraints and RLS policies. Measured at
399 / 111 / 145 / 15 objects, and identical on both paths at the time of writing.

WHY FRESH-vs-RESIDENT AND NOT FRESH-vs-DDL. Synapse compares a DDL-built database against a
chain-built one because `actions.sql` is a standalone CREATE TABLE that later migrations ALTER.
DIS has no DDL-only build path at all: 0001 applies sixteen of the nineteen files verbatim, 0013
and 0016 one each, and the nineteenth is out-of-band role bootstrap. The chain IS the DDL
applier, so "build it from the DDL instead" is not a second path — it is the same path with the
ordering re-derived, and re-deriving it here would make this test a second source of truth for
0001's MANIFEST. The honest second path is the one that actually exists in the world: a database
migrated incrementally over months.

THE STAMP GUARD IS WHAT MAKES THAT COMPARISON MEAN ANYTHING. A resident behind head is not a
"migrated reference", it is a different schema — and comparing against it would report drift that
is really just a stale devbox, or worse, agree with it. So the resident's stamp is asserted equal
to the chain head FIRST, and the failure says exactly that.

RUNTIME IS NOT THE REASON THIS IS INTEGRATION-MARKED. The full nineteen-revision chain builds in
about 1.7 seconds. It lives here because `admin_url` ERRORS rather than skips when the stack is
absent — the load-bearing-proof rule in dis_testing.plugin — so an unmarked test would fail every
stack-less `pytest` run.
"""

from __future__ import annotations

from sqlalchemy import Engine, text

from dis_testing.migration_harness import ScratchDB, alembic_head

# The eight schemas DIS's chain owns. `public` is excluded deliberately: it holds the uuidv7()
# function and the extensions, which sql/01 creates out of band before any Alembic runs, so a
# scratch DB and the resident legitimately differ there.
_SCHEMAS = ("audit", "bronze", "canonical", "config", "identity_mirror", "quarantine", "staging", "telemetry")

_IN = "(" + ", ".join(f"'{s}'" for s in _SCHEMAS) + ")"

# Four classes of object, each as a sorted set of one-line signatures. Signatures rather than
# structured rows because the assertion a reader needs is "these two texts differ HERE", and a
# set difference of strings prints that directly.
_QUERIES: dict[str, str] = {
    "columns": f"""
        SELECT table_schema || '.' || table_name || '.' || column_name
               || ' ' || data_type
               || ' null=' || is_nullable
               || ' len=' || COALESCE(character_maximum_length::text, '-')
               || ' default=' || COALESCE(column_default, '-')
          FROM information_schema.columns
         WHERE table_schema IN {_IN}
    """,
    "indexes": f"""
        SELECT schemaname || '.' || indexname || ' ' || indexdef
          FROM pg_indexes WHERE schemaname IN {_IN}
    """,
    # CHECKs, uniques, primary keys and foreign keys in one sweep. pg_get_constraintdef renders
    # the definition, so a widened CHECK shows as a text difference rather than as a same-named
    # constraint that quietly means something else.
    "constraints": f"""
        SELECT n.nspname || '.' || t.relname || '.' || c.conname || ' ' || pg_get_constraintdef(c.oid)
          FROM pg_constraint c
          JOIN pg_class t ON t.oid = c.conrelid
          JOIN pg_namespace n ON n.oid = t.relnamespace
         WHERE n.nspname IN {_IN}
    """,
    # RLS is the one class where a difference is a security difference rather than a schema one.
    # relforcerowsecurity is included because ENABLE without FORCE exempts the owner, and the two
    # are indistinguishable in pg_policies alone.
    "policies": f"""
        SELECT p.schemaname || '.' || p.tablename || '.' || p.policyname
               || ' using=' || COALESCE(p.qual, '-')
               || ' check=' || COALESCE(p.with_check, '-')
               || ' force=' || c.relforcerowsecurity::text
          FROM pg_policies p
          JOIN pg_class c ON c.relname = p.tablename
          JOIN pg_namespace n ON n.oid = c.relnamespace AND n.nspname = p.schemaname
         WHERE p.schemaname IN {_IN}
    """,
}


def _signatures(engine: Engine, sql: str) -> set[str]:
    with engine.connect() as conn:
        return {row[0] for row in conn.execute(text(sql))}


def _resident_is_at_head(engine: Engine) -> None:
    """Refuse to compare against a stale devbox.

    Without this the test is worse than absent: a resident behind head differs from a fresh chain
    in exactly the way real drift does, so it would either cry wolf or — if somebody 'fixed' it by
    relaxing the comparison — agree with fiction.
    """
    with engine.connect() as conn:
        stamp = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    head = alembic_head()
    assert stamp == head, (
        f"resident at {stamp}, head is {head} — bring the devbox to head before trusting this "
        "comparison. `make db-migrate` (or `uv run alembic upgrade head`) against 5433, then "
        "re-run. Comparing a fresh chain against a behind-head resident reports drift that is "
        "really a stale database."
    )


def test_the_resident_reference_is_at_head(admin_engine: Engine) -> None:
    """Asserted on its own as well as inside each comparison, so a stale devbox fails ONCE with
    the actionable message instead of four times with a schema diff nobody should read."""
    _resident_is_at_head(admin_engine)


def test_a_fresh_chain_and_the_migrated_reference_have_the_same_schema(
    scratch_db: ScratchDB, admin_engine: Engine
) -> None:
    """THE WHOLE-SCHEMA SWEEP. Everything the per-migration tests scope out, including the four
    revisions that have no test file of their own.

    `scratch_db` is already at head via the real chain (dis_testing.plugin), so the fresh path
    here is the same one a clean deploy takes.
    """
    _resident_is_at_head(admin_engine)

    differences: list[str] = []
    for name, sql in _QUERIES.items():
        fresh = _signatures(scratch_db.engine, sql)
        migrated = _signatures(admin_engine, sql)
        # VACUITY GUARD PER CLASS. An empty set on both sides compares equal and proves nothing —
        # a typo'd schema list or a renamed catalogue view would pass silently.
        assert migrated, f"no {name} found in the resident reference; the query stopped biting"
        only_fresh = sorted(fresh - migrated)
        only_migrated = sorted(migrated - fresh)
        if only_fresh or only_migrated:
            differences.append(
                f"\n{name}: {len(only_fresh)} only on a fresh chain, "
                f"{len(only_migrated)} only on the migrated reference"
                + "".join(f"\n  FRESH ONLY     {s}" for s in only_fresh[:10])
                + "".join(f"\n  MIGRATED ONLY  {s}" for s in only_migrated[:10])
            )

    assert not differences, (
        "a fresh database built from the chain does not match the migrated reference, so a clean "
        "deploy would differ from production. Either a migration ALTERs something its DDL file "
        "does not declare (tests/test_ddl_migration_agreement.py names that case without a "
        "database), or a DDL file was edited without a migration to carry the change to existing "
        "databases." + "".join(differences)
    )


def test_the_comparison_covers_every_schema_the_chain_creates(scratch_db: ScratchDB) -> None:
    """The schema list is a hand-kept constant, so it can fall behind the chain. 0016 added
    `telemetry` and a list written before it would have swept seven of eight while looking
    complete."""
    with scratch_db.engine.connect() as conn:
        created = {
            row[0]
            for row in conn.execute(
                text(
                    "SELECT nspname FROM pg_namespace WHERE nspname NOT LIKE 'pg_%' "
                    "AND nspname NOT IN ('information_schema', 'public')"
                )
            )
        }
    missing = created - set(_SCHEMAS)
    assert not missing, (
        f"the chain creates schemas this comparison does not sweep: {sorted(missing)}. Add them to _SCHEMAS."
    )
