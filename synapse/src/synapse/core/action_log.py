"""The append-only action log: TWO protocols, because there are two postures.

APPEND-ONLY IS ENFORCED BY WHAT THESE PROTOCOLS DO NOT HAVE. There is no ``update``, no
``delete``, no ``replace``, and no way to reach a stored event and rebind a field — events are
frozen dataclasses and the sequence handed back is a copy. A correction is a new append naming
what it supersedes (``ActionEvent.supersedes``).

That is a stronger guarantee than a table with a comment saying "do not update". A type that
offers no edit cannot be edited by someone in a hurry.

===============================================================================================
WHY TWO PROTOCOLS AND NOT ONE
===============================================================================================

A single ``ActionLog`` with both methods cannot be implemented in Postgres here, for two
separate reasons — the second is the interesting one.

FIRST, THE METHODS MUST BE ASYNC. Everything in Synapse that touches a database is async:
rls_session, every resolver, resolve(), resolve_declaration(). A sync log protocol would be
unimplementable by anything that does I/O.

SECOND, AND MORE IMPORTANTLY, ONE OBJECT WOULD HAVE TO DO TWO THINGS THAT DELIBERATELY LIVE IN
DIFFERENT ROLES. ``synapse_writer`` holds INSERT and no SELECT; ``synapse_reader`` holds SELECT
and no INSERT. That split is not incidental — it is what makes "resolvers never write" a runtime
property rather than a grep test. A single protocol would force a durable writer to carry an
``events()`` it could never implement, and ``NotImplementedError`` there is the SYMPTOM, not the
fix: a protocol with a member one implementation deliberately cannot satisfy is a broken
protocol.

So the types agree with the role posture, and THREE LAYERS SAY THE SAME THING:

    the GRANT says the writer cannot read
    the ENGINE says it
    and the TYPE says it — a writer object has no events() to call

Same discipline as the generated columns in the DDL: make the disagreement unrepresentable
rather than detectable.

``InMemoryActionLog`` IMPLEMENTS BOTH, which is what keeps it a conformance fixture rather than
a convenience. Every protocol test runs over two sets — appenders and readers — and the
in-memory log appears in both, so anything the durable implementations must do it is held to as
well.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from synapse.core.action import ActionEvent


class ActionAppender(Protocol):
    """Somewhere action events go. APPENDS ONLY — deliberately no other verb.

    A Protocol rather than a base class so a durable implementation does not inherit from a
    module in ``synapse.core``, which is forbidden a database by import-linter. The caller does
    not learn which kind of appender it has, and should not.
    """

    async def append(self, event: ActionEvent) -> bool:
        """Record one event. Returns whether it LANDED; ``False`` means it was suppressed.

        A ``bool`` even though ``synapse_writer`` holds no SELECT, because READING THE LOG and
        knowing what your own statement did are different things: ``ON CONFLICT DO NOTHING``
        reports its own ``rowcount``, which needs no SELECT grant and discloses nothing about
        any other row.

        It is NOT an invitation to read-modify-write. The value says what one INSERT did; it
        cannot be used to look up, compare or amend anything, and there is still no way to read
        the log through an appender. ``synapse.run`` uses it to record how many of a run's
        proposed actions were genuinely new, which is the difference between a re-run and a
        first run.
        """
        ...


class ActionReader(Protocol):
    """Somewhere action events come back from. READS ONLY — no append, by construction."""

    async def events(self) -> Sequence[ActionEvent]:
        """Every event in scope, in append order.

        Order is part of the contract: an append-only log whose order is unspecified cannot be
        replayed, and replay is most of the reason to keep one.
        """
        ...


class InMemoryActionLog:
    """The append-only log, in memory. Implements BOTH protocols, and is not a stub.

    It is what the unit tests use permanently, and it is the reason the protocol tests mean
    something: every appender test and every reader test runs over this as well as over the
    durable implementations, so the two cannot drift apart in what they promise.

    ``async`` despite needing no I/O. Matching the protocol is the point — an in-memory
    implementation that was sync would force the protocol to be sync, which nothing that
    does real I/O could then implement.

    ``_events`` is private and ``events()`` returns a TUPLE, so a caller cannot append by
    reaching through the accessor. Returning the live list would make ``append`` advisory and
    the append-only property a convention rather than a property.
    """

    def __init__(self) -> None:
        self._events: list[ActionEvent] = []

    async def append(self, event: ActionEvent) -> bool:
        # DELIBERATELY NOT DEDUPLICATING on event_id, and this is a real difference from the
        # durable appender, which suppresses a byte-identical retry via ON CONFLICT DO NOTHING.
        # The difference is honest rather than an inconsistency: dedup there is a property of
        # the UNIQUE INDEX, which is a database object, and reproducing it here would be a second
        # implementation of the same rule that could disagree with the first. What both DO
        # guarantee — and what the shared protocol tests check — is that nothing is ever edited
        # or removed.
        self._events.append(event)
        # ALWAYS True, and it is the honest answer rather than a stub: this log does not
        # deduplicate, so every append genuinely lands. A False here would be a claim about a
        # suppression that did not happen.
        return True

    async def events(self) -> Sequence[ActionEvent]:
        return tuple(self._events)


__all__ = ["ActionAppender", "ActionReader", "InMemoryActionLog"]
