"""The delivery ledger's read path: the session it opens, the union it builds, the counts it derives.

NO DATABASE. A recording fake drives both readers, so the SQL, the session posture and the
parameter binding are asserted offline. What that CANNOT assert is the RLS behaviour itself: that
a PLATFORM session actually widens the tenant policy's USING, and that a session without the GUC
returns zero rows. Those are properties of the applied schema.

WHICH IS WORSE HERE THAN ANYWHERE ELSE IN THIS MODULE, AND THE REASON ONE TEST BELOW ASSERTS A
CALL RATHER THAN A VALUE. See test_both_reads_open_a_platform_session.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from axon import reads
from sqlalchemy.ext.asyncio import AsyncEngine

_GRANT = Path(__file__).resolve().parents[2] / "infra" / "db-setup" / "sql" / "07_axon_reader_grant.sql"

TENANT = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
DELIVERY = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")


def _engine() -> AsyncEngine:
    """A sentinel where an engine is expected, typed for mypy. Never touched: every test patches
    rls_platform_session, which is the only thing that would open a connection."""
    return cast("AsyncEngine", object())


def _row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "scope": "PLATFORM",
        "delivery_id": DELIVERY,
        "tenant_id": None,
        "created_at": datetime(2026, 8, 11, 6, 17, 8, tzinfo=UTC),
        "channel": "email",
        "notification_class": "synapse.provision.enabled",
        "subject_kind": "synapse.provision",
        "subject_id": "019f9d6d-c032-7e03-a232-ee77299f9b5d:stockout_risk",
        "recipient": "oncall@sevyn8.example",
        "state": "accepted",
        "suppression_reason": None,
        "provider": "sendgrid",
        "failure_detail": None,
        "actor_subject": "auth0|platform-operator",
    }
    base.update(overrides)
    return base


def _counts_row(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "total": 1,
        "accepted": 1,
        "failed": 0,
        "suppressed": 0,
        "suppressed_not_onboarded": 0,
    }
    base.update(overrides)
    return base


class _FakeResult:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[dict[str, Any]]:
        return self._rows

    def one(self) -> dict[str, Any]:
        return self._rows[0]


class _RecordingConn:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any] | None]] = []
        self.opened_with: tuple[object, object] | None = None
        self._rows = rows if rows is not None else [_row()]

    async def execute(self, statement: object, params: dict[str, Any] | None = None) -> _FakeResult:
        self.calls.append((str(statement), params))
        return _FakeResult(self._rows)


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Swap rls_platform_session AT THE MODULE, so reads.py's own call site is under test.

    A test patching axon.reads's import source instead could pass while reads.py opened a raw
    connection, which against FORCE ROW LEVEL SECURITY returns zero rows and raises nothing.
    """

    def install(conn: _RecordingConn) -> None:
        @asynccontextmanager
        async def fake(engine: object, tenant: object = None):  # type: ignore[no-untyped-def]
            conn.opened_with = (engine, tenant)
            yield conn

        monkeypatch.setattr(reads, "rls_platform_session", fake)

    return install


# ---------------------------------------------------------------------------
# THE SESSION. This is the test the module exists to be safe under.
# ---------------------------------------------------------------------------


async def test_both_reads_open_a_platform_session(patched: Any) -> None:
    """ASSERTS THE CALL, NOT A ROW COUNT, AND THE REASON MUST NOT BE SIMPLIFIED AWAY.

    Under FORCE ROW LEVEL SECURITY a session that never set ``app.user_type`` matches ZERO ROWS
    and raises nothing. So for ``axon.tenant_deliveries``:

        A BROKEN SESSION AND A CORRECT EMPTY TABLE ARE BYTE-IDENTICAL, FOR AS LONG AS THE TABLE
        IS EMPTY.

    That table holds zero rows today and CAN hold none: there is no address book, no tenant
    credential and no adapter beyond email, so nothing exists that could write it. A test that
    asserted "the tenant rows come back" would therefore pass against a completely broken session,
    against a missing PLATFORM branch in the policy, and against a raw connection. It would assert
    nothing and would look like it asserted everything.

    So the assertion is structural: reads.py's own name for the helper is called, once per read,
    with ``tenant_id=None``. That is checkable offline and it is the property that will still be
    true when the tenant ledger is non-empty. The value-level assertion becomes possible in the
    change that first writes a tenant delivery, and it belongs there.

    DO NOT REPLACE THIS WITH A ROW ASSERTION while the tenant ledger is empty. It would be a
    weaker test that reads as a stronger one.
    """
    engine = _engine()

    list_conn = _RecordingConn()
    patched(list_conn)
    await reads.recent_deliveries(engine)
    assert list_conn.opened_with is not None, "recent_deliveries did not open the RLS helper at all"
    assert list_conn.opened_with == (engine, None)

    counts_conn = _RecordingConn(rows=[_counts_row()])
    patched(counts_conn)
    await reads.delivery_counts(engine)
    assert counts_conn.opened_with is not None, "delivery_counts did not open the RLS helper at all"
    assert counts_conn.opened_with == (engine, None)


def test_the_module_opens_no_raw_connection() -> None:
    """THE SECOND HALF OF THE SAME GUARD, read from the source.

    The test above proves the helper IS called. This proves nothing else is: ``engine.connect()``
    or ``engine.begin()`` anywhere in this module would be a read with no GUCs set, which on the
    tenant ledger silently returns nothing.
    """
    body = open(reads.__file__, encoding="utf-8").read()  # noqa: SIM115, PTH123
    assert "engine.connect(" not in body
    assert "engine.begin(" not in body
    # The CALL SITE form, not the bare name: the module docstring names the helper too, and a
    # count that included prose would pass on a module that had stopped calling it.
    assert body.count("async with rls_platform_session(engine, None) as conn:") == 2, (
        "both reads must open the PLATFORM helper with tenant_id=None explicitly; a default "
        "argument would put the see-all posture out of sight of the call site"
    )


# ---------------------------------------------------------------------------
# THE UNION
# ---------------------------------------------------------------------------


def test_the_list_reads_both_ledgers() -> None:
    """The surface is fleet-wide across BOTH audiences. A query naming one table would show a
    complete-looking page that omits an entire class of delivery."""
    sql = str(reads._RECENT)
    assert "axon.platform_deliveries" in sql
    assert "axon.tenant_deliveries" in sql
    assert "UNION ALL" in sql


def test_the_union_does_not_deduplicate() -> None:
    """UNION ALL, not UNION. A delivery id is minted once per delivery and a row lives in exactly
    one table, so a distinct pass can never remove a row and would only cost a sort."""
    sql = str(reads._RECENT)
    assert "UNION ALL" in sql
    assert "\n    UNION\n" not in sql


def test_the_platform_branch_synthesises_a_null_tenant() -> None:
    """axon.platform_deliveries HAS NO tenant_id COLUMN. Not omitted: a platform delivery has no
    tenant. The cast is explicit so the union's column types do not depend on branch order."""
    sql = str(reads._RECENT)
    assert "NULL::uuid      AS tenant_id" in sql


def test_the_scope_column_is_synthesised_on_both_branches() -> None:
    """A merged result is unreadable without it: two rows with the same shape and different
    isolation rules, indistinguishable. It is a literal per branch, not a stored column."""
    sql = str(reads._RECENT)
    assert "'PLATFORM'      AS scope" in sql
    assert "'TENANT'        AS scope" in sql


def test_the_list_is_ordered_newest_first_and_the_tie_is_broken() -> None:
    """created_at alone is not a total order: two deliveries in the same microsecond would come
    back in an arbitrary and unstable order. delivery_id is a UUIDv7, so the tie-break is itself
    time-ordered rather than arbitrary."""
    assert "ORDER BY created_at DESC, delivery_id DESC" in str(reads._RECENT)


def test_the_list_is_capped_and_says_so() -> None:
    """A ledger grows without bound. The cap is bound, and the truncation flag is RETURNED rather
    than left for the caller to infer by comparing against a limit it would have to hold too."""
    assert "LIMIT :limit" in str(reads._RECENT)
    assert reads._MAX_ROWS > 0


async def test_a_full_page_reports_truncation_and_a_short_one_does_not(patched: Any) -> None:
    """THE FLAG'S BOUNDARY, both sides. Asserted at the cap rather than at some fixed number, so
    moving _MAX_ROWS cannot leave this test passing against the old value."""
    patched(_RecordingConn(rows=[_row() for _ in range(reads._MAX_ROWS)]))
    _, truncated = await reads.recent_deliveries(_engine())
    assert truncated is True

    patched(_RecordingConn(rows=[_row()]))
    _, truncated = await reads.recent_deliveries(_engine())
    assert truncated is False


async def test_the_list_binds_the_cap_as_a_parameter(patched: Any) -> None:
    """Bound, not interpolated. Consistency with every other statement in this repository, and it
    is the only reason the SQL text is a constant that can be asserted at all."""
    conn = _RecordingConn()
    patched(conn)

    await reads.recent_deliveries(_engine())

    assert len(conn.calls) == 1
    assert conn.calls[0][1] == {"limit": reads._MAX_ROWS}


async def test_a_row_maps_to_the_dataclass_field_for_field(patched: Any) -> None:
    """The mapping is hand-written, so a column renamed in the SQL and not here fails at runtime
    with a KeyError on a page an operator is looking at. This is the cheap version of that."""
    patched(_RecordingConn())

    rows, _ = await reads.recent_deliveries(_engine())

    assert len(rows) == 1
    row = rows[0]
    assert row.scope == "PLATFORM"
    assert row.delivery_id == DELIVERY
    assert row.tenant_id is None
    assert row.notification_class == "synapse.provision.enabled"
    assert row.state == "accepted"
    assert row.provider == "sendgrid"
    assert row.suppression_reason is None
    assert row.failure_detail is None


async def test_a_tenant_row_carries_its_tenant_id(patched: Any) -> None:
    """THE OTHER BRANCH, exercised through the fake because it cannot yet be exercised through the
    database. This asserts the MAPPING handles a tenant row, which is a different claim from
    asserting the query returns one, and it is the only one of the two that is honest today."""
    patched(_RecordingConn(rows=[_row(scope="TENANT", tenant_id=TENANT, channel="whatsapp")]))

    rows, _ = await reads.recent_deliveries(_engine())

    assert rows[0].scope == "TENANT"
    assert rows[0].tenant_id == TENANT
    assert rows[0].channel == "whatsapp"


# ---------------------------------------------------------------------------
# THE COUNTS
# ---------------------------------------------------------------------------


def test_the_counts_are_their_own_query_over_the_whole_ledger() -> None:
    """NOT DERIVED FROM THE PAGE. The list is capped; counts derived from a capped page are a
    floor presented as a total, which is the exact defect the alerts inbox's chips record. So the
    aggregate reads both tables itself, and carries no LIMIT."""
    sql = str(reads._COUNTS)
    assert "axon.platform_deliveries" in sql
    assert "axon.tenant_deliveries" in sql
    assert "LIMIT" not in sql.upper()


def test_the_counts_break_out_channel_not_onboarded() -> None:
    """THE WHOLE POINT OF THE FOURTH CARD. Every other suppression reason describes a decision the
    platform made on purpose. channel_not_onboarded describes a CLIENT receiving nothing while the
    platform believes it is working, and nobody being told. Folded into a general suppressed count
    it is invisible."""
    sql = str(reads._COUNTS)
    assert "suppression_reason = 'channel_not_onboarded'" in sql
    assert "AS suppressed_not_onboarded" in sql


def test_the_broken_out_count_is_a_subset_of_suppressed() -> None:
    """It filters on state='suppressed' AS WELL. Without that, a reason left on a row whose state
    later changed would be counted as a suppression that is not one, and the parts would exceed
    the whole."""
    sql = str(reads._COUNTS)
    # The FILTER clause that produces suppressed_not_onboarded, read from its opening paren to
    # its reason predicate. Sliced by index rather than by a regex so a reformatting of the SQL
    # fails this loudly instead of quietly matching a different clause.
    reason_at = sql.index("AND suppression_reason = 'channel_not_onboarded'")
    clause_at = sql.rindex("count(*) FILTER (", 0, reason_at)
    assert "state = 'suppressed'" in sql[clause_at:reason_at]


def test_every_state_in_the_vocabulary_is_counted() -> None:
    """THE VOCABULARY APPEARS IN THREE PLACES: the CHECK constraint, DeliveryState, and here. The
    first two are pinned against each other in test_ledger_and_ddl.py; this pins the third, so a
    state added to both without being added here shows up as a total that does not equal the sum
    of its parts on a live surface."""
    from axon import DeliveryState

    sql = str(reads._COUNTS)
    for member in DeliveryState:
        assert f"state = '{member.value}'" in sql, (
            f"state '{member.value}' is in the vocabulary and is not counted; the cards would not "
            "sum to the total"
        )


async def test_the_counts_map_to_the_dataclass(patched: Any) -> None:
    """Including the coercion. count(*) comes back as an int from asyncpg, and the int() calls are
    there so a driver that hands back a Decimal cannot reach a template as '1E+1'."""
    patched(
        _RecordingConn(
            rows=[_counts_row(total=9, accepted=6, failed=2, suppressed=1, suppressed_not_onboarded=1)]
        )
    )

    counts = await reads.delivery_counts(_engine())

    assert counts.total == 9
    assert counts.accepted == 6
    assert counts.failed == 2
    assert counts.suppressed == 1
    assert counts.suppressed_not_onboarded == 1


async def test_the_counts_are_a_single_round_trip(patched: Any) -> None:
    """One statement, one row out. Four queries would be four points at which the figures on one
    screen could disagree with each other."""
    conn = _RecordingConn(rows=[_counts_row()])
    patched(conn)

    await reads.delivery_counts(_engine())

    assert len(conn.calls) == 1


# ---------------------------------------------------------------------------
# WHAT THE READ PATH MUST NOT DO
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("forbidden", ["INSERT", "UPDATE", "DELETE", "TRUNCATE", "ON CONFLICT"])
def test_neither_statement_writes(forbidden: str) -> None:
    """axon_reader HOLDS SELECT AND NOTHING ELSE. A write here would fail in production with a
    permission denied on a page nobody would connect to a grant file, which is precisely how 5e
    lost two days."""
    for statement in (reads._RECENT, reads._COUNTS):
        assert forbidden not in str(statement).upper()


# ---------------------------------------------------------------------------
# THE GRANT. The second layer, read from the artifact that creates it.
# ---------------------------------------------------------------------------


def test_the_grant_file_is_where_this_test_thinks_it_is() -> None:
    """THE VACUITY GUARD for the four below. A path that stopped resolving would make every one
    of them pass against an empty string."""
    assert _GRANT.is_file(), f"{_GRANT} not found"
    assert "axon_reader" in _GRANT.read_text(encoding="utf-8")


def test_the_grant_file_gives_the_reader_select_on_both_ledgers() -> None:
    """BOTH, because the surface unions both. A grant covering one would fail at runtime on a
    page that renders fine in every test in this file, since the fakes never check privileges."""
    grant = _GRANT.read_text(encoding="utf-8")
    assert "GRANT SELECT ON axon.platform_deliveries TO axon_reader;" in grant
    assert "GRANT SELECT ON axon.tenant_deliveries   TO axon_reader;" in grant
    assert "GRANT USAGE ON SCHEMA axon TO axon_reader;" in grant


@pytest.mark.parametrize("forbidden", ["INSERT", "UPDATE", "DELETE", "TRUNCATE"])
def test_the_grant_file_gives_the_reader_no_write_verb(forbidden: str) -> None:
    """A READ CREDENTIAL THAT CAN WRITE IS NOT A READ CREDENTIAL. The ledger is append-only in
    practice because axon_sender holds INSERT and nothing else; this is the other half, so that
    adding a console cannot quietly add a way to edit the evidence the console displays."""
    grant = _GRANT.read_text(encoding="utf-8")
    assert f"GRANT {forbidden}" not in grant


def test_the_reader_grant_touches_no_other_role() -> None:
    """sql/04's `REVOKE ALL ON ALL TABLES IN SCHEMA synapse FROM synapse_reader` twice stripped
    privileges a later migration had granted. Every REVOKE here names axon_reader, so running
    this file cannot take anything away from axon_sender."""
    grant = _GRANT.read_text(encoding="utf-8")
    for line in grant.splitlines():
        statement = line.strip()
        if statement.startswith("REVOKE"):
            assert "FROM axon_reader;" in statement, f"a REVOKE names another role: {statement}"
        if statement.startswith("GRANT"):
            assert "axon_reader" in statement, f"a GRANT names another role: {statement}"


def test_the_tenant_index_gap_is_recorded_where_the_query_lives() -> None:
    """THE SEQUENTIAL SCAN, PINNED SO IT STAYS EXPLAINED.

    The global ORDER BY cannot use ix_tenant_deliveries_tenant_created_at, because that index
    LEADS WITH tenant_id and this query has no tenant predicate. It costs nothing against an empty
    table, so no speculative index was added, but the next person to read an EXPLAIN here must find
    the reason and the fix rather than a mystery.

    This asserts the comment naming the fix and its trigger is still present. It is a documentation
    test on purpose: the thing being protected IS the documentation.
    """
    source = open(reads.__file__, encoding="utf-8").read()  # noqa: SIM115, PTH123
    assert "ix_tenant_deliveries_created_at" in source, "the named fix for the seq scan is gone"
    assert "THE TRIGGER IS THE FIRST TENANT SENDS" in source, (
        "the trigger for adding that index is gone; without it the comment is a note about a "
        "problem with no stated moment to act on"
    )
