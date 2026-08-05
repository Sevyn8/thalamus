"""WHICH tenants have WHICH analyses enabled, at what cadence and at what autonomy rung.

THE MISSING NOUN. ``resolve_declaration`` answers "can this analysis run for this tenant"; it
has never had anything to tell it which pairs to ask about. This module is the type side of
that answer, and ``synapse.provision`` is the data side.

ENVELOPE AND SELECTION, which is the split that dissolves the code-versus-table question rather
than adjudicating it:

    The DECLARATION holds the ENVELOPE — what an analysis is PERMITTED to do. ``max_rung`` is a
    property of the analysis's MATURITY, not of any customer. ``dead_stock`` has never been
    checked against a human judgement, so no operator should be able to promote it past shadow
    with an UPDATE.

    The TABLE holds the SELECTION — what has been CHOSEN for a tenant: enabled or not, at which
    cadence, at which rung, in which timezone, since when.

    The BOUNDARY CHECKS the binding. A provision naming a rung above its declaration's
    ``max_rung`` is refused when it is loaded, not when it is acted on.

THE THIRD INSTANCE OF A PATTERN ALREADY USED TWICE, which is why it is not a new mechanism: a
capability declares gate KINDS and an analysis binds the VALUE; a declaration declares ``emits``
and the evaluator's output is checked against it at import; now a declaration declares
``max_rung`` and a provision binds the rung. Declare the shape in code, bind the value as data,
check the binding at the boundary.

WHY THE TABLE WAS NEEDED BEFORE THERE WAS A CONSOLE (slice 8a built the read-only one, and 8b
adds the write path): ``enabled_at`` cannot
be reconstructed. An attribution study asks "how many tenant-days did we observe", and a system
that records only "enabled" has thrown the denominator away. That is the same argument the
holdout arm won in slice 4 — a fact that is free to record today and impossible to recover
afterwards.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from synapse.core.slot import Cadence

__all__ = ["Cadence", "Provision", "Rung", "rung_rank"]


class Rung(StrEnum):
    """The autonomy rung: how far a produced action is allowed to travel.

    ``SHADOW`` — compute, record, show NOBODY. The action is appended to the log and no channel,
    notification or escalation exists. This is the only rung anything is built for.

    ``SUGGEST`` — an action reaches a human. **NOTHING IMPLEMENTS THIS.** It is named here for
    two reasons, and neither is speculation about what delivery will look like:

      1. Without a rung above ``SHADOW``, the envelope check can never fire, and a guard that
         cannot fire is not a guard. Declaring the next rung is what makes
         "a provision may not exceed its declaration's max_rung" a testable statement today
         rather than a comment awaiting a second enum member.
      2. It inverts the failure mode. Enabling delivery becomes DELETING AN EXPLICIT REFUSAL —
         the orchestrator raises on any rung it cannot honour — instead of adding an enum member
         and discovering that several code paths already quietly accepted it.

    It carries no shape: no channel, no template, no recipient, no schedule. Naming a rung is
    not designing delivery, and the shape should be forced by the first real requirement.
    """

    SHADOW = "shadow"
    SUGGEST = "suggest"


# The ladder, lowest first. A separate mapping rather than an IntEnum because the VALUES are
# persisted as text in synapse.provision — an IntEnum would either store integers (unreadable in
# psql, and renumbering silently re-ranks history) or need a parallel string mapping anyway.
_RANK: Final[Mapping[Rung, int]] = MappingProxyType(
    {
        Rung.SHADOW: 0,
        Rung.SUGGEST: 1,
    }
)


def rung_rank(rung: Rung) -> int:
    """Where ``rung`` sits on the ladder. Higher is more autonomous, so comparison is ``<=``.

    Every member of ``Rung`` has a rank — checked at import below, so adding a member without
    ranking it fails on the first import rather than comparing as though it were the lowest.
    """
    return _RANK[rung]


def _check_ranks() -> None:
    """Every rung is ranked, and no two share a rank. Checked at IMPORT, like the registry's.

    There is no CI in this repo, so an invariant that is not checked at import is checked when
    somebody remembers.
    """
    unranked = sorted(rung.value for rung in Rung if rung not in _RANK)
    if unranked:
        raise AssertionError(
            f"Rung member(s) {unranked} have no rank. An unranked rung would compare as absent "
            "and the envelope check would silently admit it"
        )
    ranks = [_RANK[rung] for rung in Rung]
    if len(set(ranks)) != len(ranks):
        raise AssertionError(
            f"two rungs share a rank: {ranks}. The ladder must be a total order or 'may not "
            "exceed' has no meaning"
        )


_check_ranks()


@dataclass(frozen=True)
class Provision:
    """One tenant's enablement of one analysis. The SELECTION half.

    Frozen, and validated on construction rather than trusted: this arrives from a table an
    operator edits by hand, which is exactly the input that should not be believed. Every field
    here is either checked in ``__post_init__`` or by a CHECK constraint in the DDL, and the
    timezone is checked in both places for the reason given below.
    """

    tenant_id: UUID
    analysis_id: str
    cadence: Cadence
    rung: Rung
    timezone: str
    enabled_at: datetime

    def __post_init__(self) -> None:
        if not self.analysis_id:
            raise ValueError("a provision must name an analysis")
        if self.enabled_at.tzinfo is None or self.enabled_at.utcoffset() is None:
            raise ValueError(
                f"provision {self.analysis_id!r} for tenant {self.tenant_id} has a naive "
                f"enabled_at ({self.enabled_at!r}). It is the start of an attribution window; "
                "an ambiguous instant makes the window ambiguous"
            )
        # BELT AND BRACES WITH THE DDL TRIGGER, deliberately. The database refuses an
        # unresolvable zone on write, which makes a bad row impossible rather than detectable;
        # this catches the same thing for a Provision built in a test or by a future caller that
        # never touches the table. The failure it prevents is silent: an unresolvable zone would
        # otherwise surface as a slot computed in the wrong offset, mis-stamping every as_of.
        try:
            ZoneInfo(self.timezone)
        except (ZoneInfoNotFoundError, ValueError) as exc:
            raise ValueError(
                f"provision {self.analysis_id!r} for tenant {self.tenant_id} names timezone "
                f"{self.timezone!r}, which does not resolve. Every slot, and therefore every "
                "action's as_of, is computed in this zone"
            ) from exc
