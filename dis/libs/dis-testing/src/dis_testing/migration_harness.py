"""Reusable migration-test harness.

Importable building blocks for the migration test suite: an ephemeral scratch-DB handle and
the resident-DB fingerprint used to prove the resident dev DB (5433 / ``ithina_dis_db``) is
never mutated by a full test run. The pytest fixtures that wrap these live in the
``dis_testing`` pytest plugin; the plain functions and the ``ScratchDB`` type live here so
test modules can import the type without depending on a conftest module path.

The resident DB is only ever the Postgres server on which scratch DBs are created/dropped and a
read-only "migrated" reference. It is never the target of a downgrade/scratch migration. Port
5432 (Customer Master) is never touched.
"""

from __future__ import annotations

import hashlib
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

_REPO_ROOT = Path(__file__).resolve().parents[4]
RESIDENT_DB = "ithina_dis_db"
RESIDENT_PORT = 5433


class StackRequiredError(RuntimeError):
    """The DIS stack is required for a load-bearing migration test but is absent."""


def alembic_head() -> str:
    """The chain's head revision (file-derived, never stale)."""
    cfg = Config(str(_REPO_ROOT / "alembic.ini"))
    head = ScriptDirectory.from_config(cfg).get_current_head()
    if head is None:
        raise AssertionError("alembic migration chain has no head revision")
    return head


def require_admin_url() -> str:
    """The resident admin URL, asserted to be the DIS DB on 5433. Fail loud if absent."""
    url = os.environ.get("POSTGRES_ADMIN_URL")
    if not url:
        raise StackRequiredError(
            "POSTGRES_ADMIN_URL is not set — the migration tests need the admin role on "
            "ithina_dis_db (5433). Bring up the stack (make run-local)."
        )
    parsed = make_url(url)
    if parsed.database != RESIDENT_DB or parsed.port != RESIDENT_PORT:
        raise StackRequiredError(
            f"POSTGRES_ADMIN_URL must point at the resident DIS DB "
            f"({RESIDENT_DB} on {RESIDENT_PORT}); got database={parsed.database} port={parsed.port}."
        )
    return url


@dataclass
class ScratchDB:
    """An ephemeral scratch database brought to head, isolated from the resident DB."""

    name: str
    url: str
    engine: Engine
    env: dict[str, str]

    def alembic(self, *args: str) -> None:
        """Run ``alembic <args>`` against THIS scratch DB (never the resident one)."""
        result = subprocess.run(
            ["uv", "run", "alembic", *args],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            env=self.env,
        )
        if result.returncode != 0:
            raise AssertionError(
                f"alembic {' '.join(args)} failed on scratch DB {self.name} "
                f"(rc={result.returncode}):\nstdout: {result.stdout}\nstderr: {result.stderr}"
            )


def terminate_and_drop(server_engine: Engine, name: str, *, recreate: bool) -> None:
    """Drop (and optionally recreate) the scratch DB, terminating stray backends first."""
    autocommit = server_engine.execution_options(isolation_level="AUTOCOMMIT")
    with autocommit.connect() as conn:
        conn.execute(
            text(
                "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                "WHERE datname = :db AND pid <> pg_backend_pid()"
            ),
            {"db": name},
        )
        conn.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        if recreate:
            conn.execute(text(f"CREATE DATABASE {name}"))


def scratch_env(scratch_url: str, name: str) -> dict[str, str]:
    """Environment overrides that point alembic at the scratch DB.

    Both are required: ``env.py`` resolves the URL from ``POSTGRES_ADMIN_URL``; each migration's
    ``check_migration_target`` keys on ``POSTGRES_DB`` (Customer Master stays hard-blocked by
    name regardless of these).
    """
    return {**os.environ, "POSTGRES_ADMIN_URL": scratch_url, "POSTGRES_DB": name}


def resident_fingerprint(engine: Engine) -> tuple[str, str]:
    """``(alembic_version, schema hash)``. The hash covers every column, constraint, and index
    of every non-system schema — the structural shape a migration would change. Row data is not
    included, so data-writing integration tests do not trip the resident-untouched guard."""
    with engine.connect() as conn:
        version = conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()
        columns = conn.execute(
            text(
                "SELECT table_schema, table_name, column_name, data_type, udt_name, "
                "is_nullable, COALESCE(character_maximum_length, -1), COALESCE(column_default, '') "
                "FROM information_schema.columns "
                "WHERE table_schema NOT LIKE 'pg\\_%' AND table_schema <> 'information_schema' "
                "ORDER BY 1, 2, 3"
            )
        ).all()
        constraints = conn.execute(
            text(
                "SELECT n.nspname, c.conname, pg_get_constraintdef(c.oid) "
                "FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
                "WHERE n.nspname NOT LIKE 'pg\\_%' AND n.nspname <> 'information_schema' "
                "ORDER BY 1, 2, 3"
            )
        ).all()
        indexes = conn.execute(
            text(
                "SELECT schemaname, indexname, indexdef FROM pg_indexes "
                "WHERE schemaname NOT LIKE 'pg\\_%' AND schemaname <> 'information_schema' "
                "ORDER BY 1, 2, 3"
            )
        ).all()
    blob = repr([tuple(r) for r in columns] + [tuple(r) for r in constraints] + [tuple(r) for r in indexes])
    return str(version), hashlib.sha256(blob.encode()).hexdigest()
