"""The rate_limit_state writer on the connector-health emit (D116).

Offline: no database. A recording fake stands in for the ``rls_session`` connection, so
these assert the SQL the emit ISSUES and the binds it carries — the statement shape plus
the ``:stamp_rate_limit`` flag that decides stamp-vs-preserve.

HONESTY NOTE ON WHAT THIS PROVES. Asserting that the DO UPDATE says
``CASE WHEN CAST(:stamp_rate_limit AS BOOLEAN) ... ELSE
telemetry.connector_health.rate_limit_state END`` and that the flag is False proves the
emit ASKS Postgres to preserve. It does not execute that SQL, so it cannot prove the row is
actually left alone — only an integration test against a real table can. What these lock is
the thing a future edit is most likely to get wrong: silently turning an ignorance-preserve
into an authoritative NULL, or vice versa.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from thalamus_connector_sdk import RATE_LIMIT_EXHAUSTED, RATE_LIMIT_THROTTLED, RATE_LIMIT_UNKNOWN
from thalamus_connector_sdk.adapter import merge_rate_limit_state
from thalamus_connector_sdk.health import upsert_health_error, upsert_health_seen

_TENANT = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")
_SOURCE = "square_pos_v2"

_PRESERVE_SQL = (
    "rate_limit_state = CASE WHEN CAST(:stamp_rate_limit AS BOOLEAN) "
    "THEN EXCLUDED.rate_limit_state "
    "ELSE telemetry.connector_health.rate_limit_state END"
)


class _RecordingConn:
    """Captures the statement text + binds the emit would execute."""

    def __init__(self) -> None:
        self.sql: str = ""
        self.params: dict[str, Any] = {}

    async def execute(self, statement: Any, params: dict[str, Any]) -> None:
        self.sql = str(statement)
        self.params = params


async def _seen(**kwargs: Any) -> _RecordingConn:
    conn = _RecordingConn()
    await upsert_health_seen(conn, tenant_id=_TENANT, source_id=_SOURCE, **kwargs)  # type: ignore[arg-type]
    return conn


async def _error(**kwargs: Any) -> _RecordingConn:
    conn = _RecordingConn()
    await upsert_health_error(
        conn,  # type: ignore[arg-type]
        tenant_id=_TENANT,
        source_id=_SOURCE,
        detail="PREFLIGHT_FAILED",
        **kwargs,
    )
    return conn


# -- the column is actually written -------------------------------------------------


async def test_both_emits_carry_the_column_and_the_conditional_merge() -> None:
    for conn in (await _seen(), await _error()):
        assert "rate_limit_state" in conn.sql
        # Not a COALESCE: that would latch the first throttle forever, since the read
        # side reads any non-null as 'rate_limited'.
        assert _PRESERVE_SQL in conn.sql
        assert "COALESCE(EXCLUDED.rate_limit_state" not in conn.sql


# -- the authoritative writes -------------------------------------------------------


async def test_success_stamps_throttled() -> None:
    conn = await _seen(rate_limit_state=RATE_LIMIT_THROTTLED)
    assert conn.params["stamp_rate_limit"] is True
    assert conn.params["rate_limit_state"] == "throttled"


async def test_clean_success_stamps_null_and_clears_a_stored_posture() -> None:
    # POSITIVE CLEAR: None from a path that DID extract is "no 429 this run", not
    # ignorance. It must stamp, so a throttle recorded last run does not stick forever.
    conn = await _seen(rate_limit_state=None)
    assert conn.params["stamp_rate_limit"] is True
    assert conn.params["rate_limit_state"] is None


async def test_rate_limited_failure_stamps_exhausted() -> None:
    conn = await _error(rate_limit_state=RATE_LIMIT_EXHAUSTED)
    assert conn.params["stamp_rate_limit"] is True
    assert conn.params["rate_limit_state"] == "exhausted"


# -- the negative cases: ignorance preserves ----------------------------------------


async def test_sentinel_preserves_on_both_emits() -> None:
    # NEGATIVE CASE: the default is ignorance, so a caller that forgets to pass the
    # posture preserves rather than clears — the safe direction.
    for conn in (await _seen(), await _error()):
        assert conn.params["stamp_rate_limit"] is False
        assert conn.params["rate_limit_state"] is None
    for conn in (
        await _seen(rate_limit_state=RATE_LIMIT_UNKNOWN),
        await _error(rate_limit_state=RATE_LIMIT_UNKNOWN),
    ):
        assert conn.params["stamp_rate_limit"] is False


async def test_metadata_keeps_its_own_coalesce_merge() -> None:
    # The two columns must NOT converge on one discipline: metadata is an accumulating
    # hint (COALESCE), rate_limit_state is a current posture (CASE WHEN).
    conn = await _seen(metadata={"dropped_count": 3})
    assert "metadata = COALESCE(EXCLUDED.metadata, telemetry.connector_health.metadata)" in conn.sql
    assert conn.params["metadata"] == '{"dropped_count": 3}'


# -- the multi-domain fold ----------------------------------------------------------


def test_merge_is_most_severe_first() -> None:
    assert merge_rate_limit_state(None, None) is None
    assert merge_rate_limit_state(None, RATE_LIMIT_THROTTLED) == RATE_LIMIT_THROTTLED
    assert merge_rate_limit_state(RATE_LIMIT_THROTTLED, None) == RATE_LIMIT_THROTTLED
    assert merge_rate_limit_state(RATE_LIMIT_THROTTLED, RATE_LIMIT_THROTTLED) == RATE_LIMIT_THROTTLED
    # exhausted outranks throttled in both argument orders.
    assert merge_rate_limit_state(RATE_LIMIT_THROTTLED, RATE_LIMIT_EXHAUSTED) == RATE_LIMIT_EXHAUSTED
    assert merge_rate_limit_state(RATE_LIMIT_EXHAUSTED, RATE_LIMIT_THROTTLED) == RATE_LIMIT_EXHAUSTED
