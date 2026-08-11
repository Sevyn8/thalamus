"""Alembic environment for AXON'S OWN CHAIN.

Axon is a PEER of DIS and of Synapse, not part of either. It is the delivery plane: it holds
addresses and send state and nothing else. Under Synapse's chain every Axon schema change would
become a Synapse migration, reviewed in Synapse's runbook, for tables Synapse never reads.

THREE CHAINS, ONE DATABASE, AND THE TWO THINGS THAT MAKES NECESSARY. Both are copied from
synapse/alembic/env.py deliberately, because the reasoning transfers unchanged:

1. A DISTINCT VERSION TABLE. Each chain would otherwise claim ``public.alembic_version`` and read
   another's head as its own. Axon uses ``axon_alembic_version``.

   NOT ``version_table_schema="axon"``. Alembic creates the version table BEFORE running the
   migration that would create the schema, so a fresh database fails on the first upgrade. Synapse
   recorded that reasoning; this chain would rediscover it identically.

2. A DISTINCT URL VARIABLE. ``AXON_ADMIN_URL``, not ``SYNAPSE_ADMIN_URL`` and not DIS's
   ``POSTGRES_ADMIN_URL``. Reusing another chain's variable makes it trivially easy to point this
   one at the wrong target, which is the same reasoning that named ``SYNAPSE_READER_URL`` rather
   than reusing ``POSTGRES_URL``.

THE CHAINS ARE ORDER-INDEPENDENT. ``axon.platform_deliveries`` and ``axon.tenant_deliveries`` have
no foreign keys into any DIS or Synapse schema, deliberately: the delivery's subject is an opaque
(kind, id) pair rather than a reference. So no chain depends on another and any may run first.
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

# No models. The DDL files under axon/schemas/postgres are the source of truth and the migrations
# apply them verbatim, exactly as Synapse's and DIS's bootstraps do. Autogenerate is deliberately
# unavailable: it would invent a second description of the same schema, free to disagree.
target_metadata = None

# The version table for THIS chain. See the module docstring.
VERSION_TABLE = "axon_alembic_version"


def _resolve_admin_url() -> str:
    """Resolve the migration URL. A missing one is a hard failure, never a silent default.

    Precedence mirrors Synapse's env.py so the two behave the same way under ``make`` and under a
    bare ``uv run alembic``:

      1. ``AXON_ADMIN_URL`` from the environment.
      2. ``AXON_ADMIN_URL`` from the repo-root .env, so a bare invocation works locally.
      3. ``sqlalchemy.url`` from alembic.ini (blank by default, on purpose).
    """
    url = os.environ.get("AXON_ADMIN_URL")

    if not url:
        try:
            from dotenv import load_dotenv

            repo_root = Path(__file__).resolve().parents[2]
            load_dotenv(repo_root / ".env", override=False)
            url = os.environ.get("AXON_ADMIN_URL")
        except Exception:  # pragma: no cover - dotenv is best-effort here
            url = None

    if not url:
        url = config.get_main_option("sqlalchemy.url") or None

    if not url:
        raise RuntimeError(
            "No migration database URL. Set AXON_ADMIN_URL in the environment. It must point at "
            "the database holding the axon schema, as a role that can CREATE SCHEMA - locally "
            "ithina_dis_admin, in staging postgres (which owns the other schemas there). NOT "
            "axon_sender, which holds INSERT on one table and nothing else, and NOT "
            "SYNAPSE_ADMIN_URL or POSTGRES_ADMIN_URL, which are other chains."
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
