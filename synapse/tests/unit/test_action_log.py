"""The append-only log protocols, offline. TWO parameterised sets, one per protocol.

WHY PARAMETERISED. ``InMemoryActionLog`` appears in BOTH sets, which is what turns it from a
convenience into a CONFORMANCE FIXTURE: every property a durable implementation must have, the
in-memory one is held to as well, and neither can quietly drift from the other's promises.

WHY TWO SETS AND NOT ONE. The protocol split in slice 5 because a single ``ActionLog`` forced a
durable writer to carry an ``events()`` it could never implement — ``synapse_writer`` holds
INSERT and no SELECT. A ``NotImplementedError`` there would have been the symptom of a broken
protocol, so the types now match the posture: appenders append, readers read, and the in-memory
log does both.

The DURABLE implementations are constructed here but never connected — the properties tested at
this level are structural (what a type offers, what it refuses). Behaviour against a real
database lives in the integration suite, which is where an idempotent retry can actually be
observed.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from synapse.core.action import Action, ActionEvent, Provenance, Verb
from synapse.core.action_log import ActionAppender, ActionReader, InMemoryActionLog
from synapse.core.holdout import Arm
from synapse.persistence.action_log_postgres import (
    PostgresActionAppender,
    PostgresActionReader,
)

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
AS_OF = date(2026, 8, 5)


def _event(n: int, *, supersedes: UUID | None = None) -> ActionEvent:
    return ActionEvent(
        event_id=UUID(int=n),
        recorded_at=datetime(2026, 8, 5, 9, n, tzinfo=UTC),
        action=Action(
            target={"tenant_id": str(TENANT), "sku_id": f"SKU-{n}"},
            verb=Verb.REVIEW,
            quantity_at_stake=Decimal("40.000"),
            expires_on=AS_OF + timedelta(days=30),
            arm=Arm.TREATMENT,
            provenance=Provenance(
                declaration_id="dead_stock",
                declaration_version="0.1.0",
                capability_versions={"current_state": "0.1.0"},
                thresholds={"stale_after_days": 90},
                as_of=AS_OF,
            ),
        ),
        supersedes=supersedes,
    )


# Every appender and every reader. The durable ones are given None for an engine because these
# tests never connect — what is under test is the SHAPE each type offers.
APPENDERS: list[Callable[[], object]] = [
    InMemoryActionLog,
    lambda: PostgresActionAppender(None, TENANT),  # type: ignore[arg-type]
]
READERS: list[Callable[[], object]] = [
    InMemoryActionLog,
    lambda: PostgresActionReader(None, TENANT),  # type: ignore[arg-type]
]

_MUTATORS = {"update", "delete", "remove", "replace", "clear", "pop", "insert", "extend", "truncate"}


# ---------------------------------------------------------------------------
# Every APPENDER
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("build", APPENDERS)
def test_an_appender_offers_no_way_to_edit_or_remove(build: Callable[[], object]) -> None:
    """APPEND-ONLY PROVED BY ABSENCE, which is the strongest form available in a type.

    A table with a comment saying "do not update" is what canonical's event tables had before
    migration 0019, and it cost one 328-row upload becoming 1640 rows. A type that offers no
    edit cannot be edited by someone in a hurry.
    """
    offered = {name for name in dir(build()) if not name.startswith("_")}
    assert offered & _MUTATORS == set(), f"offers {sorted(offered & _MUTATORS)}"


@pytest.mark.parametrize("build", APPENDERS)
def test_an_appender_appends(build: Callable[[], object]) -> None:
    assert callable(getattr(build(), "append", None))


def test_the_durable_appender_cannot_be_asked_to_read() -> None:
    """THE POINT OF THE SPLIT, and the reason it is better than NotImplementedError.

    ``synapse_writer`` holds INSERT and no SELECT, so a durable appender could never implement
    ``events()``. Rather than carrying a method that raises, it has no such method — so asking
    is an AttributeError at the call site instead of a runtime surprise, and the type agrees
    with the grant and the engine instead of contradicting them.
    """
    appender = PostgresActionAppender(None, TENANT)  # type: ignore[arg-type]
    assert not hasattr(appender, "events")


# ---------------------------------------------------------------------------
# Every READER
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("build", READERS)
def test_a_reader_offers_no_way_to_edit_or_remove(build: Callable[[], object]) -> None:
    offered = {name for name in dir(build()) if not name.startswith("_")}
    assert offered & _MUTATORS == set(), f"offers {sorted(offered & _MUTATORS)}"


def test_the_durable_reader_cannot_be_asked_to_append() -> None:
    """The other half of the split: a reader holds an engine with no INSERT grant anywhere, and
    now no method that would want one."""
    reader = PostgresActionReader(None, TENANT)  # type: ignore[arg-type]
    assert not hasattr(reader, "append")


# ---------------------------------------------------------------------------
# The in-memory log, which satisfies BOTH — the conformance fixture
# ---------------------------------------------------------------------------


def test_the_in_memory_log_satisfies_both_protocols() -> None:
    """If it ever stopped, the parameterised sets above would silently shrink to one real
    implementation each and stop being conformance tests at all."""
    log = InMemoryActionLog()
    # The ANNOTATIONS are the assertion: mypy --strict rejects these bindings if the class stops
    # satisfying either protocol, which is a stronger check than anything assertable at runtime.
    appender: ActionAppender = log
    reader: ActionReader = log
    assert isinstance(appender, InMemoryActionLog)
    assert isinstance(reader, InMemoryActionLog)


async def test_events_returns_a_copy_so_the_log_cannot_be_appended_through_it() -> None:
    """Returning the live list would make ``append`` advisory and append-only a convention."""
    log = InMemoryActionLog()
    await log.append(_event(1))
    snapshot = await log.events()
    assert isinstance(snapshot, tuple)
    assert len(await log.events()) == 1


async def test_a_correction_is_a_new_event_naming_what_it_supersedes() -> None:
    """D33's shape one layer up: an append-only log replays to any point in time, and an edited
    row destroys the history that makes a study possible."""
    log = InMemoryActionLog()
    original = _event(1)
    await log.append(original)
    await log.append(_event(2, supersedes=original.event_id))

    events = await log.events()
    assert len(events) == 2, "a correction ADDS; it does not replace"
    assert events[1].supersedes == original.event_id


async def test_the_log_preserves_append_order() -> None:
    """Order is part of the reader contract: a log whose order is unspecified cannot be
    replayed, and replay is most of the reason to keep one."""
    log = InMemoryActionLog()
    for i in range(1, 6):
        await log.append(_event(i))
    assert [event.event_id.int for event in await log.events()] == [1, 2, 3, 4, 5]


async def test_the_in_memory_log_does_not_deduplicate_and_that_is_deliberate() -> None:
    """A REAL DIFFERENCE FROM THE DURABLE APPENDER, pinned so it is a decision rather than a gap.

    The durable one suppresses a byte-identical retry via ON CONFLICT over a unique index.
    Reproducing that here would be a SECOND implementation of the same rule, free to disagree
    with the first — and the rule belongs to the index, which is a database object. What both
    guarantee, and what the shared tests above check, is that nothing is ever edited or removed.
    """
    log = InMemoryActionLog()
    await log.append(_event(1))
    await log.append(_event(1))
    assert len(await log.events()) == 2
