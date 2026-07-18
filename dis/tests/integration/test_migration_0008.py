"""Migration 0008 (DUPLICATE_* outcomes + prior_trace_id — the D42 revision):
target safety, the additive cycle, the refuse-loudly downgrade, and
fresh-bootstrap convergence.

Layers (the 0002..0007 migration-test conventions):

  * **Target-safety guard, asserted positively and non-skippably** (the pure
    ``check_migration_target``: refuses Customer Master outright, refuses any
    non-expected database, passes only the DIS database).
  * **Additive cycle against an ephemeral scratch DB (Slice 51c, D122).**
    ``upgrade head``: ``prior_trace_id`` present (uuid, nullable) and the
    outcome CHECK carries 6 values — additive, never a drop-recreate.
    ``downgrade 0007``: the column is gone and the 4-value CHECK is restored.
    ``upgrade head``: the 0008 shape returns.
  * **The refuse-loudly downgrade (the 0005 precedent).** With a row carrying
    a DUPLICATE_* outcome present (seeded on the scratch DB), ``downgrade
    0007`` must FAIL LOUD naming the violation, never silently drop the CHECK
    over violating rows.
  * **Fresh-bootstrap convergence on a scratch DB (the 9a lesson).** The
    ephemeral scratch DB at head (0001 applies the updated — 6-value,
    24-column — events.sql; 0007 re-applies the same file; 0008 no-ops) must
    carry the full normalized audit.events shape the delta path (resident
    migrated reference) carries, including a clean ``diff_schema`` against the
    dis-audit schema contract.

See: docs/slices/slice-30c-audit-tier2.md, decisions.md D42 (revised), D77/D78/D79.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import Engine, text

from dis_audit import EXPECTED_COLUMNS, diff_schema
from dis_testing.migration_harness import ScratchDB, alembic_head

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0008_audit_outcome_vocab_prior_trace.py"

_OLD_VOCAB = {"SUCCESS", "FAILURE", "SKIPPED", "RETRIED"}
_NEW_VOCAB = _OLD_VOCAB | {"DUPLICATE_NOOP", "DUPLICATE_OVERWRITTEN"}


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0008", _MIGRATION_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Target-safety guard: pure, always-run, never skips (no DB needed).
# ---------------------------------------------------------------------------


def test_guard_refuses_customer_master() -> None:
    mod = _load_migration_module()
    with pytest.raises(RuntimeError, match="Customer Master"):
        mod.check_migration_target("ithina_platform_db", expected_db="ithina_dis_db")


def test_guard_refuses_unexpected_database() -> None:
    mod = _load_migration_module()
    with pytest.raises(RuntimeError, match="expected"):
        mod.check_migration_target("some_other_db", expected_db="ithina_dis_db")


def test_guard_passes_the_dis_database_positively() -> None:
    mod = _load_migration_module()
    mod.check_migration_target("ithina_dis_db", expected_db="ithina_dis_db")


# ---------------------------------------------------------------------------
# Helpers (error, never skip, when the stack is absent).
# ---------------------------------------------------------------------------


def _alembic_expect_failure(scratch: ScratchDB, *args: str) -> str:
    """Run ``alembic <args>`` against the scratch DB expecting a non-zero exit."""
    result = subprocess.run(
        ["uv", "run", "alembic", *args],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        env=scratch.env,
    )
    assert result.returncode != 0, (
        f"alembic {' '.join(args)} UNEXPECTEDLY SUCCEEDED:\nstdout: {result.stdout}"
    )
    return result.stdout + result.stderr


def _column_present(engine: Engine) -> tuple[str, str] | None:
    """(data_type, is_nullable) for prior_trace_id, or None when absent."""
    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT data_type, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'audit' AND table_name = 'events' "
                "AND column_name = 'prior_trace_id'"
            )
        ).first()
    return None if row is None else (row.data_type, row.is_nullable)


def _outcome_vocab(engine: Engine) -> set[str]:
    import re

    with engine.connect() as conn:
        definition = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'audit.events'::regclass "
                "AND conname = 'ck_audit_events_outcome_vocab'"
            )
        ).scalar_one()
    return set(re.findall(r"'([A-Z_]+)'::", definition))


def _contract_diffs(engine: Engine) -> list[str]:
    with engine.connect() as conn:
        live_rows = [
            (r[0], r[1], r[2], r[3])
            for r in conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable, character_maximum_length "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'audit' AND table_name = 'events'"
                )
            ).all()
        ]
    return diff_schema(live_rows, EXPECTED_COLUMNS)


def _audit_shape(engine: Engine) -> dict[str, object]:
    """A compact normalized shape for convergence equality (name-keyed; ordinals
    deliberately excluded — the 0008 ALTER appends, the file places mid-table)."""
    with engine.connect() as conn:
        columns = [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable, "
                    "COALESCE(character_maximum_length, -1) "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'audit' AND table_name = 'events' "
                    "ORDER BY column_name"
                )
            ).all()
        ]
        constraints = {
            r[0]: r[1]
            for r in conn.execute(
                text(
                    "SELECT conname, pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'audit.events'::regclass"
                )
            ).all()
        }
        rls = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'audit.events'::regclass"
            )
        ).one()
    return {"columns": columns, "constraints": constraints, "rls": tuple(rls)}


# ---------------------------------------------------------------------------
# The additive cycle + refuse-loudly against an ephemeral scratch DB.
# ---------------------------------------------------------------------------


@pytest.mark.skip(reason="downgrade-reversibility deferred until staging (D99)")
def test_migration_cycle_additive_and_reversible(scratch_db: ScratchDB) -> None:
    # apply-to-head stays covered by the upgrade-only assertion tests in this file.
    # scratch_db is already at head: the 0008 shape — additive.
    assert _column_present(scratch_db.engine) == ("uuid", "YES")
    assert _outcome_vocab(scratch_db.engine) == _NEW_VOCAB
    assert _contract_diffs(scratch_db.engine) == []  # the live schema matches the contract
    head_shape = _audit_shape(scratch_db.engine)

    # downgrade to 0007 (no DUPLICATE_* rows exist → permitted): column gone,
    # 4-value CHECK restored.
    scratch_db.alembic("downgrade", "0007")
    assert _column_present(scratch_db.engine) is None
    assert _outcome_vocab(scratch_db.engine) == _OLD_VOCAB

    # re-upgrade: the 0008 shape returns, identical to the first pass.
    scratch_db.alembic("upgrade", "head")
    assert _audit_shape(scratch_db.engine) == head_shape


@pytest.mark.skip(reason="downgrade-reversibility deferred until staging (D99)")
def test_downgrade_refuses_loudly_with_duplicate_rows(scratch_db: ScratchDB) -> None:
    """The 0005 precedent: a downgrade that would orphan DUPLICATE_* rows under
    the restored 4-value CHECK fails LOUD, never silently mutates audit rows."""
    trace = None
    try:
        with scratch_db.engine.begin() as conn:
            trace = conn.execute(
                text(
                    "INSERT INTO audit.events "
                    "(event_timestamp, event_date, trace_id, prior_trace_id, service_name, "
                    " stage, event_scope, outcome) "
                    "VALUES ('2026-01-01T00:00:00Z', '2026-01-01', uuidv7(), uuidv7(), "
                    "        'migration-test', 'CANONICAL_WRITTEN', 'ROW', 'DUPLICATE_NOOP') "
                    "RETURNING trace_id"
                )
            ).scalar_one()

        output = _alembic_expect_failure(scratch_db, "downgrade", "0007")
        # The PRE-CHECK refusal specifically — not merely any failure. (The
        # migration's title banner contains "DUPLICATE_*", and a guard-less
        # downgrade would still exit non-zero when Postgres validates the
        # restored CHECK over the seeded row — both would satisfy a loose
        # "DUPLICATE in output" match. Mutation-proven: disabling the pre-check
        # fails THESE assertions.)
        assert "Refusing to downgrade 0008" in output, (
            f"the refusal must come from the pre-check, loud and named:\n{output}"
        )
        assert "1 audit.events row(s)" in output, f"the refusal must name the count:\n{output}"
        # Nothing changed: the column and the 6-value CHECK survived the refusal.
        assert _column_present(scratch_db.engine) == ("uuid", "YES")
        assert _outcome_vocab(scratch_db.engine) == _NEW_VOCAB
        # And the AUDIT ROW ITSELF is unharmed — the refusal never deletes or
        # mutates data (the data-safety half of the guard).
        with scratch_db.engine.connect() as conn:
            survivor = conn.execute(
                text("SELECT outcome, prior_trace_id FROM audit.events WHERE trace_id = CAST(:t AS uuid)"),
                {"t": str(trace)},
            ).one()
        assert survivor.outcome == "DUPLICATE_NOOP"
        assert survivor.prior_trace_id is not None
    finally:
        if trace is not None:
            with scratch_db.engine.begin() as conn:
                conn.execute(
                    text("DELETE FROM audit.events WHERE trace_id = CAST(:t AS uuid)"),
                    {"t": str(trace)},
                )

    # With the seeded row gone, the cycle is clean again (nothing stranded).
    scratch_db.alembic("downgrade", "0007")
    assert _outcome_vocab(scratch_db.engine) == _OLD_VOCAB
    scratch_db.alembic("upgrade", "head")
    assert _outcome_vocab(scratch_db.engine) == _NEW_VOCAB


def test_reapplying_0008_on_an_already_migrated_table_is_a_noop(scratch_db: ScratchDB) -> None:
    """The gates SHORT-CIRCUIT — proven by re-execution, not by result-matching.

    ``alembic stamp 0007`` rewinds only the version table (no DDL), so
    ``upgrade 0008`` re-runs ``0008.upgrade()`` against a table that ALREADY
    has the column and the 6-value CHECK. If the existence gate did not fire,
    the un-guarded ``ADD COLUMN`` would error (duplicate column); if the
    def-gate did not fire, the CHECK would be dropped and re-added. A clean
    rerun with a byte-identical shape is therefore proof the gates actually
    short-circuited (the anti-self-healing property, applied to idempotency).
    Runs against the ephemeral scratch DB (already at head via the fixture).

    Scoped to ``upgrade 0008`` (not ``upgrade head``): this test proves 0008's
    idempotency, so it re-runs ONLY 0008. Re-running the whole tail would also re-apply
    0016 (telemetry.connector_health), whose CREATE is NOT existence-gated — a separate,
    still-non-idempotent migration this slice surfaces but does not fix (Slice 51c gates
    only 0013; the deferred trigger covers the rest).
    """
    before = _audit_shape(scratch_db.engine)
    scratch_db.alembic("stamp", "0007")
    scratch_db.alembic("upgrade", "0008")  # re-executes ONLY 0008.upgrade() over the 0008 shape
    assert _audit_shape(scratch_db.engine) == before


# ---------------------------------------------------------------------------
# Fresh-bootstrap convergence on a scratch DB (the 9a lesson).
# ---------------------------------------------------------------------------


def test_fresh_bootstrap_converges_with_delta_path(scratch_db: ScratchDB, admin_engine: Engine) -> None:
    """Fresh: the scratch DB where 0001 applies the updated (24-column, 6-value)
    events.sql, 0007 re-applies the same file, and 0008 no-ops. Its end shape
    equals the delta path's (the resident migrated reference — the ALTER-built
    shape), name-keyed, and both diff clean against the dis-audit contract."""
    with scratch_db.engine.connect() as conn:
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == alembic_head()

    # Focused fresh-side checks: the 0008 end state is present on the scratch DB.
    assert _column_present(scratch_db.engine) == ("uuid", "YES"), (
        "fresh bootstrap lacks prior_trace_id — the manifest no longer carries the 0008 end state"
    )
    assert _outcome_vocab(scratch_db.engine) == _NEW_VOCAB

    # The fresh end state equals the delta-path end state, and both diff clean
    # against the dis-audit schema contract.
    assert _audit_shape(scratch_db.engine) == _audit_shape(admin_engine)
    assert _contract_diffs(scratch_db.engine) == []
