"""The append-only action log: a protocol with no mutating method, and a real implementation.

APPEND-ONLY IS ENFORCED BY WHAT THIS PROTOCOL DOES NOT HAVE. There is no ``update``, no
``delete``, no ``replace``, and no way to reach a stored event and rebind a field — the events
are frozen dataclasses and the sequence handed back is a copy. A correction is a new append that
names what it supersedes (``ActionEvent.supersedes``).

That is a stronger guarantee than a table with a comment saying "do not update", which is what
canonical's event tables had before migration 0019 and which cost 328 rows becoming 1640. A
type that offers no edit cannot be edited by someone in a hurry.

WHY THERE IS NO ``synapse`` SCHEMA IN THIS SLICE. A table written before anything writes to it
is the signal-history artifact in canonical: a DDL implying a compute job that never existed,
verified four ways including zero rows in both schemas, and still on the ledger. A migration is
worth writing once the shape has been exercised — which is what this module and its tests do —
and not before.

``InMemoryActionLog`` IS NOT A STUB. It is the log the tests use, permanently, and it is what
makes the append-only property demonstrable rather than asserted. A persistent implementation
later satisfies the same protocol; nothing that consumes a log needs to know which it has.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Protocol

from synapse.core.action import ActionEvent


class ActionLog(Protocol):
    """Somewhere action events go. APPENDS ONLY — deliberately no other verb.

    A Protocol rather than a base class so a persistent implementation does not inherit from a
    module in ``synapse.core``, which is forbidden a database by import-linter. The reader of a
    log does not learn which kind it has, and should not.
    """

    def append(self, event: ActionEvent) -> None:
        """Record one event. Never rejects on grounds of content — that is the type's job."""
        ...

    def events(self) -> Sequence[ActionEvent]:
        """Every event recorded, in append order.

        Order is part of the contract: an append-only log whose order is unspecified cannot be
        replayed, and replay is most of the reason to keep one.
        """
        ...


class InMemoryActionLog:
    """The append-only log, in memory. Real implementation, used by the tests.

    ``_events`` is private and ``events()`` returns a TUPLE, so a caller cannot append by
    reaching through the accessor — returning the live list would make ``append`` advisory and
    the append-only property a convention rather than a property.
    """

    def __init__(self) -> None:
        self._events: list[ActionEvent] = []

    def append(self, event: ActionEvent) -> None:
        # DELIBERATELY NOT DEDUPLICATING on event_id. A log that silently drops a repeat is a log
        # that has decided a repeat is a mistake, and it is not this layer's call: two events with
        # one id is a bug in whoever minted them, and it should be visible in the log rather than
        # quietly absent from it. The same reasoning that made DIS's duplicate detection AUDIT
        # rather than suppress, before 0019 made suppression a deliberate write gate.
        self._events.append(event)

    def events(self) -> Sequence[ActionEvent]:
        return tuple(self._events)


__all__ = ["ActionLog", "InMemoryActionLog"]
