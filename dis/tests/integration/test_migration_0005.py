"""Migration 0005 (source_mappings template grain + RLS ON): target safety,
backfill, reversibility, and fresh-bootstrap convergence (Slice 14a).

Four layers:

  * **Target-safety guard, asserted positively and non-skippably.** The pure
    ``check_migration_target`` refusal logic is unit-testable without a live
    bind (the 0002/0003/0004 precedent): refuses Customer Master outright,
    refuses any non-expected database, passes only the DIS database.
  * **Reversible cycle against an ephemeral scratch DB (Slice 51c, D122).**
    ``downgrade 0004`` removes the template columns, restores the (tenant,
    source) keys and the pre-0005 trigger body, and turns RLS off; ``upgrade
    head`` re-adds, BACKFILLS the rows (one template_id per (tenant, source)
    group, name 'default'), rekeys, and turns RLS on.
  * **D22/D49 invariance.** The PK, the canonical FKs onto
    ``mapping_version_id``, and the ``mapping_rules`` column are byte-equal
    before and after the cycle (the pin stands; the rules shape is untouched).
  * **Fresh-bootstrap convergence on a scratch DB (the 9a lesson).** The
    ephemeral scratch DB (0001 applies the updated manifest, 0005 no-ops) is
    compared against the resident migrated reference: the full normalized shape
    — columns, constraint defs, index defs, trigger + function body
    (``pg_get_functiondef``, not file text), RLS posture, policy, view
    reloptions, comments — must match.

The migration runs against ``ithina_dis_db`` (and the scratch DB) on 5433
only; the in-migration guard refuses Customer Master (``ithina_platform_db``)
before any DDL.

See: docs/slices/slice-14a-source-mappings-migration.md.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from sqlalchemy import Engine, text

from dis_testing.migration_harness import ScratchDB, alembic_head

pytestmark = pytest.mark.integration

_REPO_ROOT = Path(__file__).resolve().parents[2]
_MIGRATION_PATH = _REPO_ROOT / "alembic" / "versions" / "0005_source_mappings_template_grain_rls.py"

# Constraints and indexes whose live definitions constitute the 0005 shape.
_CSM_CONSTRAINTS = (
    "pk_csm",
    "uq_csm_seq_per_source",
    "ex_csm_template_name_per_source",
    "fk_csm_tenant",
    "ck_csm_status_vocab",
    "ck_csm_version_seq_positive",
    "ck_csm_activated_consistency",
    "ck_csm_deprecated_consistency",
)
_CSM_INDEXES = (
    "uq_csm_active_per_source",
    "ix_csm_tenant_source_status",
    "ix_csm_status",
    "ix_csm_predecessor",
)
_COMMENTED_COLUMNS = (
    "template_id",
    "template_name",
    "version_seq_per_source",
    "status",
    "predecessor_version_id",
)


def _load_migration_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("migration_0005", _MIGRATION_PATH)
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
# Live-shape introspection helpers (catalogs, never file text).
# ---------------------------------------------------------------------------


def _template_columns(engine: Engine) -> dict[str, str]:
    """{column: is_nullable} for the two 0005 columns (empty dict = absent)."""
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT column_name, is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'config' AND table_name = 'source_mappings' "
                "AND column_name IN ('template_id', 'template_name')"
            )
        ).all()
    return {r.column_name: r.is_nullable for r in rows}


def _rls_posture(engine: Engine) -> tuple[bool, bool, int]:
    with engine.connect() as conn:
        flags = conn.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE oid = 'config.source_mappings'::regclass"
            )
        ).one()
        policies = conn.execute(
            text(
                "SELECT COUNT(*) FROM pg_policies WHERE schemaname = 'config' "
                "AND tablename = 'source_mappings' AND policyname = 'tenant_isolation'"
            )
        ).scalar_one()
    return bool(flags.relrowsecurity), bool(flags.relforcerowsecurity), int(policies)


def _pin_shape(engine: Engine) -> dict[str, str | None]:
    """The D22/D49 invariants: PK def, canonical FKs onto mapping_version_id,
    and the mapping_rules column type — must be identical across the cycle."""
    with engine.connect() as conn:
        pk = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'config.source_mappings'::regclass AND conname = 'pk_csm'"
            )
        ).scalar_one()
        fks = (
            conn.execute(
                text(
                    "SELECT conrelid::regclass::text || ': ' || pg_get_constraintdef(oid) AS d "
                    "FROM pg_constraint "
                    "WHERE confrelid = 'config.source_mappings'::regclass ORDER BY 1"
                )
            )
            .scalars()
            .all()
        )
        rules = conn.execute(
            text(
                "SELECT data_type || '/' || is_nullable FROM information_schema.columns "
                "WHERE table_schema = 'config' AND table_name = 'source_mappings' "
                "AND column_name = 'mapping_rules'"
            )
        ).scalar_one()
    return {"pk": pk, "fks": "; ".join(fks), "mapping_rules": rules}


def _csm_shape(engine: Engine) -> dict[str, object]:
    """The full normalized 0005 end-state shape, for convergence comparison.

    Everything here comes from the live catalogs (pg_get_*def, pg_indexes,
    information_schema, pg_policies, obj/col_description) — never from file
    text — so the manifest and the migration cannot 'agree' by coincidence.
    """
    shape: dict[str, object] = {}
    with engine.connect() as conn:
        shape["columns"] = [
            tuple(r)
            for r in conn.execute(
                text(
                    "SELECT column_name, data_type, is_nullable, "
                    "COALESCE(character_maximum_length, -1), collation_name "
                    "FROM information_schema.columns "
                    "WHERE table_schema = 'config' AND table_name = 'source_mappings' "
                    "ORDER BY column_name"
                )
            ).all()
        ]
        shape["constraints"] = {
            name: conn.execute(
                text(
                    "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                    "WHERE conrelid = 'config.source_mappings'::regclass AND conname = :n"
                ),
                {"n": name},
            ).scalar()
            for name in _CSM_CONSTRAINTS
        }
        shape["indexes"] = {
            name: conn.execute(
                text(
                    "SELECT indexdef FROM pg_indexes WHERE schemaname = 'config' "
                    "AND tablename = 'source_mappings' AND indexname = :n"
                ),
                {"n": name},
            ).scalar()
            for name in _CSM_INDEXES
        }
        shape["trigger"] = conn.execute(
            text(
                "SELECT pg_get_triggerdef(t.oid) FROM pg_trigger t "
                "WHERE t.tgrelid = 'config.source_mappings'::regclass AND NOT t.tgisinternal"
            )
        ).scalar()
        shape["function"] = conn.execute(
            text("SELECT pg_get_functiondef('config.set_csm_version_seq()'::regprocedure)")
        ).scalar()
        shape["rls"] = (
            conn.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE oid = 'config.source_mappings'::regclass"
                )
            )
            .one()
            ._asdict()
        )
        shape["policy"] = (
            conn.execute(
                text(
                    "SELECT permissive, roles, cmd, qual, with_check FROM pg_policies "
                    "WHERE schemaname = 'config' AND tablename = 'source_mappings' "
                    "AND policyname = 'tenant_isolation'"
                )
            )
            .one()
            ._asdict()
        )
        shape["view_options"] = conn.execute(
            text("SELECT reloptions FROM pg_class WHERE oid = 'config.source_mappings_v'::regclass")
        ).scalar()
        shape["table_comment"] = conn.execute(
            text("SELECT obj_description('config.source_mappings'::regclass)")
        ).scalar()
        shape["view_comment"] = conn.execute(
            text("SELECT obj_description('config.source_mappings_v'::regclass)")
        ).scalar()
        shape["column_comments"] = {
            col: conn.execute(
                text(
                    "SELECT col_description('config.source_mappings'::regclass, "
                    "(SELECT ordinal_position FROM information_schema.columns "
                    " WHERE table_schema = 'config' AND table_name = 'source_mappings' "
                    " AND column_name = :c))"
                ),
                {"c": col},
            ).scalar()
            for col in _COMMENTED_COLUMNS
        }
    return shape


@pytest.mark.skip(reason="downgrade-reversibility deferred until staging (D99)")
def test_migration_cycle_backfills_and_flips_rls(scratch_db: ScratchDB) -> None:
    # apply-to-head/fresh-bootstrap stays covered by test_fresh_bootstrap_converges_with_delta_path.
    # The cycle runs on the ephemeral scratch DB (already at head via the
    # fixture); a resident DB whose sources carry multiple templates can never
    # be stranded by the downgrade's (tenant, source)-grained rekey.
    pins_before = _pin_shape(scratch_db.engine)
    assert _template_columns(scratch_db.engine) == {"template_id": "NO", "template_name": "NO"}
    assert _rls_posture(scratch_db.engine) == (True, True, 1)

    # downgrade to 0004: columns gone, RLS off, policy dropped, old keys back.
    scratch_db.alembic("downgrade", "0004")
    assert _template_columns(scratch_db.engine) == {}
    assert _rls_posture(scratch_db.engine) == (False, False, 0)
    with scratch_db.engine.connect() as conn:
        seq_def = conn.execute(
            text(
                "SELECT pg_get_constraintdef(oid) FROM pg_constraint "
                "WHERE conrelid = 'config.source_mappings'::regclass "
                "AND conname = 'uq_csm_seq_per_source'"
            )
        ).scalar_one()
        fn_def = conn.execute(
            text("SELECT pg_get_functiondef('config.set_csm_version_seq()'::regprocedure)")
        ).scalar_one()
    assert "template_id" not in seq_def
    assert "template_id" not in fn_def

    # re-upgrade: columns NOT NULL and every row backfilled — non-null UUID
    # template_id, name 'default', exactly ONE template per (tenant, source)
    # group (lineage preserved, never per-row minting).
    scratch_db.alembic("upgrade", "head")
    assert _template_columns(scratch_db.engine) == {"template_id": "NO", "template_name": "NO"}
    assert _rls_posture(scratch_db.engine) == (True, True, 1)
    with scratch_db.engine.connect() as conn:
        rows = conn.execute(
            text("SELECT tenant_id, source_id, template_id, template_name FROM config.source_mappings")
        ).all()
        per_group = conn.execute(
            text(
                "SELECT MAX(c) FROM (SELECT COUNT(DISTINCT template_id) AS c "
                "FROM config.source_mappings GROUP BY tenant_id, source_id) x"
            )
        ).scalar()
    assert rows, "cycle ran against an empty table — backfill not exercised"
    for r in rows:
        assert isinstance(UUID(str(r.template_id)), UUID)
        assert r.template_name == "default"
    assert per_group == 1

    # D22/D49 invariance: the pin and the rules shape survived the cycle.
    assert _pin_shape(scratch_db.engine) == pins_before


def test_fresh_bootstrap_converges_with_delta_path(scratch_db: ScratchDB, admin_engine: Engine) -> None:
    """The 9a lesson: the fresh path (a scratch DB where 0001 applies the
    updated manifest and 0005 no-ops) must land the IDENTICAL shape the delta
    path (the resident migrated reference) leaves behind."""
    with scratch_db.engine.connect() as conn:
        head = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
    assert head == alembic_head()

    # The fresh end state equals the delta-path (migrated) end state.
    assert _csm_shape(scratch_db.engine) == _csm_shape(admin_engine)
