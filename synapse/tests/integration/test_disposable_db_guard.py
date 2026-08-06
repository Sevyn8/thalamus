"""The live write tests must not be armable against real staging. Proof, with no DSN required.

IT RUNS UNARMED, WHICH IS THE POINT. Every other module in this directory skips without a DSN — so
a guard test that needed one would be absent in exactly the situation where somebody most needs to
know the guard works. Nothing below opens a connection or reads the environment: the guard is a
pure function over a DSN string, so these run on every `make test`, armed or not.

It sits beside the conftest it tests rather than in tests/unit because --import-mode=importlib
gives a module no way to reach a conftest in a sibling package; see tests/__init__.py.

WHAT WENT WRONG WITHOUT IT. ``synapse.actions`` is append-only: the trigger refuses DELETE for
every role including the owner. The live tests mint fixture rows with a fresh uuid4 per run
(``PROBE-{uuid4}``, ``SKU-BASELINE-{uuid4}``, ``SKU-IDEMPOTENCY-{uuid4}``), so each armed run
against staging added rows that can never be removed. Thirteen exist. They are invisible to
tenant views through RLS and they stay; this guard stops the count growing.
"""

from __future__ import annotations

import pytest

from .conftest import assert_disposable

_REAL_DB = "postgresql+psycopg://synapse_writer:pw@10.55.0.3:5432/thalamus?sslmode=require"


def test_the_real_staging_dsn_is_refused() -> None:
    """The exact DSN an operator already has in their shell — the one that wrote the thirteen."""
    with pytest.raises(RuntimeError, match="real staging"):
        assert_disposable(_REAL_DB, var="SYNAPSE_WRITER_URL")


def test_the_real_database_is_refused_from_any_host() -> None:
    """dbname alone is enough. Catches a proxy on 127.0.0.1, a private DNS name, or any alias
    that reaches `thalamus` by a route this list has never heard of."""
    with pytest.raises(RuntimeError, match="real staging"):
        assert_disposable("postgresql+psycopg://u:pw@127.0.0.1:5432/thalamus", var="SYNAPSE_WRITER_URL")


def test_the_real_instance_is_refused_whatever_the_database_is_called() -> None:
    """THE SECOND CHECK, AND IT IS NOT REDUNDANT. A second real database on the same instance —
    created later, named anything — is refused without anyone remembering to extend the dbname
    list. The host check ages better than the name check."""
    with pytest.raises(RuntimeError, match="real staging"):
        assert_disposable("postgresql+psycopg://u:pw@10.55.0.3:5432/some_other_db", var="SYNAPSE_ADMIN_URL")


def test_a_disposable_local_dsn_is_allowed() -> None:
    """THE BASELINE, and without it every refusal above would also pass against a guard that
    rejected everything — the failure mode this project has already paid for."""
    assert_disposable(
        "postgresql+psycopg://u:pw@localhost:5433/synapse_test_abc123", var="SYNAPSE_WRITER_URL"
    )


def test_an_unset_dsn_is_allowed() -> None:
    """Unset means the live tests skip, which is the honest outcome for an unarmed run. Only an
    ARMED run against the real ledger is the problem."""
    assert_disposable(None, var="SYNAPSE_WRITER_URL")
    assert_disposable("", var="SYNAPSE_WRITER_URL")


def test_the_refusal_never_prints_the_password() -> None:
    """The message reaches pytest output, which reaches CI logs. It names host and dbname so the
    reader can see WHICH database was refused, and nothing else."""
    with pytest.raises(RuntimeError) as caught:
        assert_disposable(_REAL_DB, var="SYNAPSE_WRITER_URL")
    message = str(caught.value)
    assert "pw" not in message.replace("SYNAPSE_WRITER_URL", "")
    assert "10.55.0.3" in message and "thalamus" in message


def test_both_write_dsns_are_guarded_at_collection_time() -> None:
    """THE WIRING, not just the function. A guard nothing calls is the guard-that-never-fires
    failure, and it is invisible: the tests would pass and still pollute.

    Asserted at module scope in both writer files, so it raises during COLLECTION — before any
    engine is constructed and before a single row can be written.
    """
    from pathlib import Path

    integration = Path(__file__).resolve().parent
    for name in ("test_action_log_live.py", "test_orchestrator_live.py"):
        source = (integration / name).read_text(encoding="utf-8")
        calls = [line for line in source.splitlines() if line.startswith("assert_disposable(")]
        assert len(calls) == 2, (
            f"{name} should guard both write DSNs at module scope, found {len(calls)}: {calls}"
        )
        assert "SYNAPSE_WRITER_URL" in source and "SYNAPSE_ADMIN_URL" in source


def test_the_reader_dsn_is_deliberately_not_guarded() -> None:
    """Stated so a future contributor does not "fix" the omission.

    The five resolver tests read REAL tenant data from staging and that is their entire purpose —
    pointing them at an empty disposable database would turn them into vacuous passes. They
    cannot pollute: synapse_reader holds SELECT and nothing else, enforced by grant rather than
    by convention.
    """
    from pathlib import Path

    integration = Path(__file__).resolve().parent
    for name in ("test_action_log_live.py", "test_orchestrator_live.py"):
        source = (integration / name).read_text(encoding="utf-8")
        assert "assert_disposable(READER_DSN" not in source
