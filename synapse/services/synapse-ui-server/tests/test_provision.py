"""Enablement: the pre-flight, the constants, the timezone, the gate, and the three states.

WHAT THIS FILE IS FOR. Slice 5e turned a hand-run psql procedure into an endpoint, and almost all
of that procedure's value is in things a form discards by default: two pre-flight checks, two
columns that are not parameters, a timezone chosen once, and the absence of a disable. Each of
those has a test here, and each test names the failure it prevents rather than the branch it
covers, because the failures are the reason the code has this shape.

WHAT IS ASSERTED ELSEWHERE, deliberately not restated:
  - that the write surface is one statement in one module per credential, that cadence and rung
    are unreachable from a caller, and that both writes open a tenant-scoped session
    (test_no_write_path.py, which is where the whole-service claims live)
  - that synapse_reader can read every object reads.py names (test_grants_cover_reads.py)
  - that the timezone trigger and the RLS policy actually bite against a real Postgres. THEY ARE
    NOT COVERED HERE AND CANNOT BE: a fake connection cannot refuse a row. See the note at the
    bottom of this file, which says so rather than leaving the gap to be assumed away.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast
from uuid import UUID

import pytest
from synapse_ui_server import provision as provision_module
from synapse_ui_server.provision import (
    CADENCE,
    RUNG,
    EnablementRefusedError,
    enable_analysis,
)

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

TENANT = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
WHEN = datetime(2026, 8, 9, 4, 0, tzinfo=UTC)


class _Scalar:
    """One scalar result. Two accessors because the pre-flight uses both, and the difference
    matters: scalar_one_or_none is the FATAL branch's "no such tenant", scalar_one is a count
    that always exists."""

    def __init__(self, value: Any) -> None:
        self._value = value

    def scalar_one_or_none(self) -> Any:
        return self._value

    def scalar_one(self) -> Any:
        return self._value


class _RecordingConn:
    """Answers each statement in the order provision.py issues them, and records the lot.

    RESPONSES ARE KEYED ON THE STATEMENT, not on call order. Keying on order would make a test
    pass against an implementation that ran the pre-flight AFTER the insert, which is precisely
    the defect the whole design is about.
    """

    def __init__(
        self, *, tenant_name: str | None, positions: int, on_insert: Exception | None = None
    ) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        # Set by the `patched` fixture when the session is opened. Declared here so the
        # assertion about WHICH tenant the session was scoped to is type-checked.
        self.opened_with: tuple[Any, Any] = (None, None)
        self._tenant_name = tenant_name
        self._positions = positions
        self._on_insert = on_insert

    async def execute(self, statement: object, params: dict[str, Any] | None = None) -> _Scalar:
        sql = str(statement)
        self.calls.append((sql, params))
        if "identity_mirror.tenants" in sql:
            return _Scalar(self._tenant_name)
        if "store_sku_current_position" in sql:
            return _Scalar(self._positions)
        if "INSERT INTO synapse.provision" in sql:
            if self._on_insert is not None:
                raise self._on_insert
            return _Scalar(None)
        raise AssertionError(f"provision.py issued an unexpected statement: {sql}")


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Swap rls_session at the MODULE, so provision.py's own call site is under test.

    Patching elsewhere could pass while provision.py opened a raw connection, which against
    FORCE ROW LEVEL SECURITY means the pre-flight count returns zero and raises nothing, and the
    endpoint would warn "no canonical positions" about a tenant with thousands. Same reasoning as
    the reads fixtures, and the same trap.
    """

    def install(conn: _RecordingConn) -> _RecordingConn:
        @asynccontextmanager
        async def fake(engine: object, tenant: object):  # type: ignore[no-untyped-def]
            conn.opened_with = (engine, tenant)
            yield conn

        monkeypatch.setattr(provision_module, "rls_session", fake)
        return conn

    return install


async def _enable(conn: _RecordingConn, **overrides: Any) -> Any:
    kwargs: dict[str, Any] = {
        "tenant_id": TENANT,
        "analysis_id": "dead_stock",
        "timezone": "Asia/Kolkata",
        "enabled_at": WHEN,
    }
    kwargs.update(overrides)
    # The engine is never touched: rls_session is patched at the module, so this stands in
    # for one purely to prove provision.py passes through whatever it is given.
    return await enable_analysis(cast("AsyncEngine", object()), **kwargs)


# ---------------------------------------------------------------------------
# THE PRE-FLIGHT. Both branches, and they are not the same problem.
# ---------------------------------------------------------------------------


async def test_an_unknown_tenant_is_fatal_and_nothing_is_inserted(patched) -> None:  # type: ignore[no-untyped-def]
    """THE CASE THE PRE-FLIGHT EXISTS FOR, AND IT IS INVISIBLE WITHOUT IT.

    An unknown tenant UUID inserts fine, enumerates fine, and produces a perfectly healthy run
    with zero actions every day for ever. Nothing goes red, no alert fires, and the only symptom
    is a client who never hears anything, which is indistinguishable from a client with nothing
    to say.

    ASSERTS THE INSERT WAS NEVER ISSUED, not merely that the call raised. A version that inserted
    and then raised would pass a raises-only test and would leave the row behind, because the
    rollback is a property of the transaction rather than of the exception.
    """
    conn = patched(_RecordingConn(tenant_name=None, positions=0))

    with pytest.raises(EnablementRefusedError, match="never goes red") as caught:
        await _enable(conn)

    assert caught.value.reason == "unknown_tenant"
    assert not any("INSERT INTO" in sql for sql, _ in conn.calls), (
        "the insert was issued for a tenant that is not in the mirror"
    )


async def test_a_tenant_with_no_positions_warns_and_proceeds(patched) -> None:  # type: ignore[no-untyped-def]
    """THE OTHER BRANCH, AND IT MUST NOT BE FATAL. Enabling ahead of ingestion is a real thing to
    want, and refusing it would make the console useless for exactly the client who has just been
    onboarded. A silent zero is the thing being prevented, not a zero.

    THIS IS NIBPL IN STAGING: zero products against two declared analyses, which is why the WARN
    branch is exercised on real data rather than only here.
    """
    conn = patched(_RecordingConn(tenant_name="NIBPL", positions=0))

    outcome = await _enable(conn)

    assert outcome.warning is not None
    assert "NIBPL" in outcome.warning
    assert "correct if ingestion is still to come" in outcome.warning
    assert any("INSERT INTO synapse.provision" in sql for sql, _ in conn.calls), (
        "the warning branch refused the write; it must proceed"
    )


async def test_a_tenant_with_positions_carries_no_warning(patched) -> None:  # type: ignore[no-untyped-def]
    """THE BASELINE, and without it the test above passes against an implementation that warns
    unconditionally. TestCo in staging has 15 products, which is the happy path."""
    conn = patched(_RecordingConn(tenant_name="TestCo", positions=15))

    outcome = await _enable(conn)

    assert outcome.warning is None
    assert outcome.canonical_positions == 15
    assert outcome.tenant_name == "TestCo"


async def test_the_preflight_runs_before_the_insert_on_the_same_connection(patched) -> None:  # type: ignore[no-untyped-def]
    """ONE TRANSACTION, OR THE PRE-FLIGHT IS ADVICE.

    Two things are asserted and both are load-bearing. THE ORDER: a check issued after the write
    cannot prevent it. THE SINGLE CONNECTION: rls_session opens one transaction that commits on
    clean exit and rolls back on exception, so a check on a different connection would leave a
    window in which the fact checked can change, and a raise would no longer undo the insert.
    """
    conn = patched(_RecordingConn(tenant_name="TestCo", positions=15))

    await _enable(conn)

    order = [sql for sql, _ in conn.calls]
    assert len(order) == 3, f"expected exactly the pre-flight plus the insert, got {len(order)}"
    assert "identity_mirror.tenants" in order[0]
    assert "store_sku_current_position" in order[1]
    assert "INSERT INTO synapse.provision" in order[2]


async def test_the_session_is_scoped_to_the_tenant_being_enabled(patched) -> None:  # type: ignore[no-untyped-def]
    """RLS, AND IT IS FORCED RATHER THAN CHOSEN.

    synapse.provision's policy is WITH CHECK (tenant_id = app.tenant_id), so a PLATFORM session
    sets the tenant GUC to '' and the insert matches no row and is refused. The same session is
    what makes the WARN branch's count real, since canonical is FORCE RLS too.

    THE TENANT PASSED TO rls_session MUST BE THE TENANT IN THE ROW. If they ever diverge the
    policy refuses the write, which is the correct outcome and an unhelpful way to discover a
    bug; this catches it here.
    """
    conn = patched(_RecordingConn(tenant_name="TestCo", positions=15))

    await _enable(conn)

    _engine, scoped_to = conn.opened_with
    assert scoped_to == TENANT

    inserted = next(params for sql, params in conn.calls if "INSERT INTO" in sql)
    assert inserted is not None
    assert inserted["tenant_id"] == str(TENANT)


# ---------------------------------------------------------------------------
# THE CONSTANTS. A value that cannot be typed cannot be mistyped.
# ---------------------------------------------------------------------------


async def test_the_insert_always_binds_daily_and_shadow(patched) -> None:  # type: ignore[no-untyped-def]
    """THE FLEET-BREAKING ONE, asserted on the parameters actually sent.

    test_no_write_path.py asserts that cadence and rung are not reachable from a caller. This
    asserts the other half: that the values which DO reach the database are the two safe ones.
    Both are needed, because a signature with no rung parameter and a statement binding 'suggest'
    from a module constant would pass the first test and stop the fleet's 04:00 sweep.
    """
    conn = patched(_RecordingConn(tenant_name="TestCo", positions=15))

    await _enable(conn)

    inserted = next(params for sql, params in conn.calls if "INSERT INTO" in sql)
    assert inserted is not None
    assert inserted["cadence"] == "daily" == CADENCE
    assert inserted["rung"] == "shadow" == RUNG


def test_suggest_is_permitted_by_the_ddl_and_must_never_be_written() -> None:
    """THE REASON THE CONSTANT IS NOT ENOUGH ON ITS OWN, pinned so it cannot be forgotten.

    ck_provision_rung permits ('shadow', 'suggest'), so the DATABASE would accept 'suggest'
    happily. Nothing implements it: there is no delivery of any kind. A dropdown built by reading
    the CHECK constraint, which is the obvious way to build one, would offer a value that passes
    every database constraint and refuses the whole enumeration at load.

    So this asserts the gap between what the DDL allows and what the code writes, which is the
    thing a reader has to know before touching either.
    """
    from pathlib import Path

    # provision.py -> synapse_ui_server -> src -> synapse-ui-server -> services -> synapse
    ddl = (
        Path(provision_module.__file__).resolve().parents[4] / "schemas" / "postgres" / "provision.sql"
    ).read_text(encoding="utf-8")
    assert "CHECK (rung IN ('shadow', 'suggest'))" in ddl, (
        "the rung vocabulary changed; re-read whether RUNG here is still the only safe member"
    )
    assert RUNG == "shadow"


# ---------------------------------------------------------------------------
# THE ANALYSIS ID. Fifth safety property: the blast radius is the whole fleet.
# ---------------------------------------------------------------------------


async def test_an_undeclared_analysis_is_refused_before_any_connection_opens(patched) -> None:  # type: ignore[no-untyped-def]
    """AN UNKNOWN analysis_id REFUSES THE WHOLE SWEEP FOR EVERY TENANT.

    check_envelope raises synapse.core.errors.ProvisionRefusedError when any provisioned id is
    absent from
    the declarations, and the orchestrator loads the table as ONE LIST, so the refusal takes the
    entire enumeration rather than the offending row. Identical blast radius to a wrong rung, and
    the DDL cannot help: ck_provision_analysis_named only requires a non-empty string.

    NOTHING WAS ISSUED, not even the pre-flight. The check is free and needs no transaction.
    """
    conn = patched(_RecordingConn(tenant_name="TestCo", positions=15))

    with pytest.raises(EnablementRefusedError, match="WHOLE enumeration") as caught:
        await _enable(conn, analysis_id="dead_stcok")

    assert caught.value.reason == "unknown_analysis"
    assert conn.calls == []


async def test_the_declared_ids_come_from_the_registry_not_a_list_here(patched) -> None:  # type: ignore[no-untyped-def]
    """THE BASELINE FOR THE TEST ABOVE, and a guard against a hardcoded allow-list.

    Every id the registry declares must be enableable, or an analysis could ship and be
    unprovisionable for a reason nobody would look for. Asserted by enabling each of them.
    """
    from synapse.registry import declared_analysis_ids

    declared = declared_analysis_ids()
    assert declared, "the registry declares nothing; this test would be vacuous"

    for analysis_id in declared:
        conn = patched(_RecordingConn(tenant_name="TestCo", positions=15))
        outcome = await _enable(conn, analysis_id=analysis_id)
        assert outcome.analysis_id == analysis_id


# ---------------------------------------------------------------------------
# THE TIMEZONE. Chosen once, and an unresolvable one must be LOUD.
# ---------------------------------------------------------------------------


async def test_an_unresolvable_timezone_is_refused_before_any_connection_opens(patched) -> None:  # type: ignore[no-untyped-def]
    """THE LAST LINE OF DEFENCE, not the primary gate. The route checks the offered set first;
    this validates anyway, because a module callable from anywhere validates its own inputs."""
    conn = patched(_RecordingConn(tenant_name="TestCo", positions=15))

    with pytest.raises(EnablementRefusedError, match="THIS SERVICE") as caught:
        await _enable(conn, timezone="Mars/Olympus_Mons")

    assert caught.value.reason == "bad_timezone"
    assert conn.calls == []


async def test_the_message_says_which_timezone_database_refused(patched) -> None:  # type: ignore[no-untyped-def]
    """DEFECT 3 OF THE 5e TIMEZONE FIX, PINNED SO IT CANNOT COME BACK.

    This message used to be a near-copy of the trigger's: "timezone 'X' does not resolve. Every
    slot, and therefore every action's as_of, is computed in this zone". On staging that 422 was
    produced HERE, by Python's tzdata, for Asia/Calcutta, which POSTGRES WOULD HAVE ACCEPTED. So
    the console attributed a refusal to a database that never saw the value, in a module whose own
    comments argue the trigger is the only authority that speaks for the database the row lands in.

    THREE THINGS ARE ASSERTED and each is one of the message's jobs: name which of the three tz
    databases refused, say the other two were not reached, and name the deprecated-alias cause so
    an operator staring at a real city name knows why it is missing.

    AND ONE THING IS ASSERTED ABSENT: the trigger's own sentence. That text is still passed
    through verbatim on the DBAPIError path, where the database really did speak, and having two
    sources produce the same words is what made the misattribution invisible.
    """
    conn = patched(_RecordingConn(tenant_name="TestCo", positions=15))

    with pytest.raises(EnablementRefusedError) as caught:
        await _enable(conn, timezone="Mars/Olympus_Mons")

    message = str(caught.value)
    assert "THIS SERVICE's copy of the IANA database" in message
    assert "Python's zoneinfo" in message
    assert "not refused by Postgres" in message
    assert "DEPRECATED IANA ALIAS" in message
    assert "/timezones" in message
    assert "Every slot" not in message, (
        "the validator is again wearing the trigger's sentence. The trigger says that, this does "
        "not, and the whole defect was that an operator could not tell them apart"
    )


async def test_the_triggers_own_message_is_surfaced_not_swallowed(patched) -> None:  # type: ignore[no-untyped-def]
    """THE CASE PYTHON CANNOT CATCH, AND THE ONE THE OPERATOR HAS TO SEE.

    Three timezone databases are in play and they can disagree: the BROWSER's, which populates
    the picker; PYTHON's tzdata, which the check above uses; and POSTGRES's, which is the only one
    that speaks for the row. A zone can be offerable and resolvable in two of them and refused by
    the third, and the trigger is where that surfaces.

    THE MESSAGE IS PASSED THROUGH VERBATIM because it says more than this module knows: it names
    the column, the value, and the consequence ("Every slot, and therefore every action as_of, is
    computed in this zone"). Replacing it with a tidier sentence would be the console telling an
    operator less than the database told it, about a value that cannot be changed afterwards.
    """
    trigger_message = (
        'synapse.provision.timezone "America/Nuuk" does not resolve. Every slot, and therefore '
        "every action as_of, is computed in this zone; an unresolvable one would shift them "
        "silently rather than fail"
    )
    conn = patched(
        _RecordingConn(
            tenant_name="TestCo",
            positions=15,
            on_insert=_dbapi_error(trigger_message, sqlstate="22023"),
        )
    )

    with pytest.raises(EnablementRefusedError) as caught:
        await _enable(conn, timezone="America/Nuuk")

    assert caught.value.reason == "bad_timezone"
    assert trigger_message in str(caught.value), (
        "the trigger's message was replaced. It names the value and the consequence, and the "
        "console has nothing better to say about a zone it cannot change later"
    )


async def test_a_database_error_that_is_not_the_timezone_trigger_is_re_raised(patched) -> None:  # type: ignore[no-untyped-def]
    """MATCHED ON SQLSTATE, NOT ON MESSAGE TEXT, and this is what proves it.

    An RLS violation (42501) or a check failure is not a bad timezone, and dressing one up as one
    would send an operator to change a value that is already correct. The trigger's wording has
    already been edited once, when a stray %L was printing 'Mars/Olympus_MonsL', so matching the
    sentence would break the next time somebody improves it.
    """
    rls_violation = _dbapi_error(
        'new row violates row-level security policy for table "provision"', sqlstate="42501"
    )
    conn = patched(_RecordingConn(tenant_name="TestCo", positions=15, on_insert=rls_violation))

    with pytest.raises(Exception) as caught:
        await _enable(conn)

    assert not isinstance(caught.value, EnablementRefusedError), (
        "an RLS violation was reported as a bad timezone"
    )


def _dbapi_error(message: str, *, sqlstate: str) -> Exception:
    """A DBAPIError shaped like the ones psycopg raises, carrying a real sqlstate.

    BUILT RATHER THAN MOCKED so the code under test unwraps `.orig` and reads `.sqlstate` exactly
    as it does in production. A Mock would answer any attribute and would pass against an
    implementation that read the wrong one.
    """
    from sqlalchemy.exc import DBAPIError

    class _OrigError(Exception):
        def __init__(self) -> None:
            super().__init__(message)
            self.sqlstate = sqlstate

    return DBAPIError("INSERT INTO synapse.provision", {}, _OrigError())


# ---------------------------------------------------------------------------
# IDEMPOTENCY AND THE ABSENCE OF RE-ENABLE
# ---------------------------------------------------------------------------


def test_the_insert_is_idempotent_and_cannot_resurrect_a_disabled_pair() -> None:
    """ON CONFLICT DO NOTHING, PINNED ON THE SQL, and it does two jobs at once.

    RE-ENABLING IS A NO-OP AT THE DATABASE. A pair that was deliberately disabled has a row, so
    the conflict fires and the insert is suppressed: re-running never resurrects one. That is the
    same guarantee provision_analysis.sql gives, and it is why the console must establish the
    three states through the reader rather than treating a 201 as evidence a row appeared.

    AND THERE IS NO DO UPDATE. `ON CONFLICT DO UPDATE` is one word away and would silently
    re-enable a disabled pair, overwriting the enablement window and corrupting the attribution
    denominator for the gap with no error anywhere. That is the single most dangerous edit
    available in this file, so it is asserted rather than trusted.
    """
    sql = str(provision_module._ENABLE)
    assert "ON CONFLICT ON CONSTRAINT pk_provision DO NOTHING" in sql
    assert "DO UPDATE" not in sql.upper(), (
        "the insert became an upsert. That silently re-enables a disabled pair and overwrites "
        "its enablement window; the denominator for the gap becomes wrong with no error"
    )


def test_the_module_offers_no_way_to_disable_or_re_enable() -> None:
    """THE ABSENCE, ASSERTED. Enforced three deep: no function here, no UPDATE in the grant, and
    a 409 on the route. This is the first layer, and it is the one a well-meaning follow-up slice
    would add to without noticing the other two.

    NOT A STYLE RULE. synapse.provision holds ONE window per (tenant, analysis), so clearing
    disabled_at loses the fact that there was a gap. provision.sql names the append-only
    enablement history as the fix and names its trigger: THE FIRST DISABLE.
    """
    exported = set(provision_module.__all__)
    for forbidden in ("disable_analysis", "reenable_analysis", "set_timezone", "update_provision"):
        assert forbidden not in exported
        assert not hasattr(provision_module, forbidden)


def test_the_grant_file_gives_the_provisioner_no_update() -> None:
    """THE SECOND LAYER, read from the artifact that creates it.

    A code-only guarantee is one merge from being untrue. This asserts that the grant file
    actually revokes UPDATE, so "the console cannot disable a tenant" is a property of the
    database rather than of provision.py's exports.
    """
    from pathlib import Path

    # ... -> synapse -> the monorepo root
    repo_root = Path(provision_module.__file__).resolve().parents[5]
    grant = (repo_root / "infra" / "db-setup" / "sql" / "05_synapse_provisioner_grant.sql").read_text(
        encoding="utf-8"
    )
    assert "REVOKE UPDATE, DELETE, TRUNCATE ON synapse.provision FROM synapse_provisioner;" in grant
    assert "GRANT INSERT ON synapse.provision TO synapse_provisioner;" in grant
    # And the two SELECTs the pre-flight needs, which is the whole reason this role is wider than
    # the one sentence everyone wanted to write.
    assert "GRANT SELECT ON identity_mirror.tenants TO synapse_provisioner;" in grant
    assert "GRANT SELECT ON canonical.store_sku_current_position TO synapse_provisioner;" in grant
    # NOT SELECT ON THE TABLE IT WRITES. That would let the enablement credential read every
    # customer's configuration back, and it is what the endpoint uses synapse_reader for.
    assert "GRANT SELECT ON synapse.provision TO synapse_provisioner" not in grant


def test_the_grant_file_revokes_only_from_its_own_role() -> None:
    """F9 AGAIN, PRE-EMPTED. sql/04 twice stripped privileges a later migration had granted,
    because a re-runnable hand-run file carried `REVOKE ALL ON ALL TABLES ... FROM synapse_reader`
    and the pair was only wrong together.

    sql/05 must never be able to do that to anyone. Every schema-wide REVOKE in it names
    synapse_provisioner, so whatever a future migration grants to the other roles, re-running this
    file cannot take it away. test_grants_cover_reads.py checks the reader specifically; this
    checks the shape.
    """
    import re as _re
    from pathlib import Path

    # ... -> synapse -> the monorepo root
    repo_root = Path(provision_module.__file__).resolve().parents[5]
    grant = (repo_root / "infra" / "db-setup" / "sql" / "05_synapse_provisioner_grant.sql").read_text(
        encoding="utf-8"
    )
    body = "\n".join(line for line in grant.splitlines() if not line.strip().startswith("--"))

    blanket = _re.findall(r"REVOKE\s+ALL\s+ON\s+ALL\s+\w+\s+IN\s+SCHEMA\s+\w+\s+FROM\s+([^;]+);", body, _re.I)
    assert blanket, "the parser found no blanket revokes; it has stopped biting"
    for grantees in blanket:
        assert grantees.strip() == "synapse_provisioner", (
            f"sql/05 revokes schema-wide from {grantees.strip()!r}. It may only ever narrow its "
            "own role, or it becomes the second instance of the sql/04 pairing defect"
        )


# =================================================================================================
# WHAT THIS FILE CANNOT COVER, STATED RATHER THAN LEFT TO BE ASSUMED
# =================================================================================================
# A checker that does not document what it cannot see is the same defect it exists to prevent, so:
#
#   1. THE RLS POLICY ACTUALLY REFUSING A WRITE. A fake connection cannot enforce WITH CHECK.
#      test_the_session_is_scoped_to_the_tenant_being_enabled proves the right session helper is
#      opened with the right tenant, which is the code half; the database half needs Postgres.
#      Verify 5 and 6 in 05_synapse_provisioner_grant.sql are the manual form.
#   2. THE TIMEZONE TRIGGER ACTUALLY FIRING. The test above proves the error is surfaced when the
#      database raises it, using a real DBAPIError shape. It does not prove the trigger exists or
#      that it raises 22023, which is a property of the applied DDL.
#   3. THE GRANT ACTUALLY APPLYING. The two tests above read the FILE. Nothing here proves it was
#      run, or that re-running it left the posture the verification block describes.
#   4. THE CM GATE AGAINST A REAL CM. test_cm_permissions.py drives every failure mode against a
#      fake transport, which is the right level for "does it fail closed". Whether cm-backend
#      answers this tuple for this token is a live pair.
#
# ALL FOUR ARE [live] ROWS IN test_grants_cover_reads.py's pair enumeration, and the standing rule
# for those is one real call in the slice that creates the path, not a static check.
