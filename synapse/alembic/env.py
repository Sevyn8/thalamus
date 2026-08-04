"""Alembic environment for SYNAPSE'S OWN CHAIN.

Synapse is a PEER of DIS, not part of it (D1), and the schema of record is where that has
teeth. Under DIS's chain every Synapse schema change would become a DIS migration, reviewed in
DIS's runbook and tested by DIS's suite, for a table DIS never reads.

TWO CHAINS, ONE DATABASE, AND THE TWO THINGS THAT MAKES NECESSARY:

1. A DISTINCT VERSION TABLE. Both chains would otherwise claim ``public.alembic_version`` and
   each would read the other's head as its own. Synapse uses ``synapse_alembic_version``.

   NOT ``version_table_schema="synapse"``, which is the obvious-looking alternative and does not
   work: alembic creates the version table BEFORE running the migration that would create the
   schema, so a fresh database fails on the first upgrade. Found by reasoning it through rather
   than by discovering it against a real database, but it is the kind of thing that only shows
   up when someone tries it.

2. A DISTINCT URL VARIABLE. ``SYNAPSE_ADMIN_URL``, not DIS's ``POSTGRES_ADMIN_URL`` — reusing
   the DIS variable would make it trivially easy to point this chain at the wrong target, the
   same reasoning that named ``SYNAPSE_READER_URL`` rather than reusing ``POSTGRES_URL``.

THE CHAINS ARE ORDER-INDEPENDENT. ``synapse.actions`` has no foreign keys into any DIS schema
(see the DDL header for why an append-only log must not), so neither chain depends on the
other and either may run first.
"""

from __future__ import annotations

import os
from logging.config import fileConfig
from pathlib import Path

from sqlalchemy import engine_from_config, pool

from alembic import context

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# No models: the DDL files under synapse/schemas/postgres are the source of truth and the
# migrations apply them verbatim, exactly as DIS's 0001 bootstrap does. Autogenerate is
# deliberately not available — it would invent a second description of the same schema.
target_metadata = None

# The version table for THIS chain. See the module docstring: a shared name would make each
# chain read the other's head.
VERSION_TABLE = "synapse_alembic_version"


def _resolve_admin_url() -> str:
    """Resolve the migration URL. A missing one is a hard failure, never a silent default.

    Precedence mirrors DIS's env.py so the two behave the same way under ``make`` and under a
    bare ``uv run alembic``:

      1. ``SYNAPSE_ADMIN_URL`` from the environment.
      2. ``SYNAPSE_ADMIN_URL`` from the repo-root .env, so a bare invocation works locally.
      3. ``sqlalchemy.url`` from alembic.ini (blank by default, on purpose).
    """
    url = os.environ.get("SYNAPSE_ADMIN_URL")

    if not url:
        try:
            from dotenv import load_dotenv

            repo_root = Path(__file__).resolve().parents[2]
            load_dotenv(repo_root / ".env", override=False)
            url = os.environ.get("SYNAPSE_ADMIN_URL")
        except Exception:  # pragma: no cover - dotenv is best-effort here
            url = None

    if not url:
        url = config.get_main_option("sqlalchemy.url") or None

    if not url:
        raise RuntimeError(
            "No migration database URL. Set SYNAPSE_ADMIN_URL in the environment. "
            "It must point at the database holding the synapse schema, as a role that can "
            "CREATE SCHEMA — locally ithina_dis_admin, in staging postgres (which owns the "
            "other schemas there). NOT synapse_writer, which holds INSERT and nothing else, "
            "and NOT POSTGRES_ADMIN_URL, which is DIS's chain."
        )
    return url


_ADMIN_URL = _resolve_admin_url()
config.set_main_option("sqlalchemy.url", _ADMIN_URL)


def run_migrations_offline() -> None:
    context.configure(
        url=_ADMIN_URL,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table=VERSION_TABLE,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table=VERSION_TABLE,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
