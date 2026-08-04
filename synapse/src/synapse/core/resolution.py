"""The THREE outcomes of asking for a capability. Pure types; no DB, no SQL.

THE PROBLEM THIS SOLVES IS A TYPE PROBLEM, not an oversight. A registry whose lookup
returns ``Resolver | None`` has exactly two words available, so the third outcome —
"the resolver is registered, and this tenant has twelve days of the sixty it needs" —
has nowhere to go and lands as ``None``, indistinguishable from "no such capability".
The operator console then renders "unavailable" for both, and an operator who is 48
days from an answer cannot tell themselves apart from one who will never get one.

So the fix is that the return type MUST NOT be optional:

- ``Satisfied`` — the resolver exists and every declared precondition is met, for THIS
  scope, as measured just now.
- ``Unregistered`` — no entry. Carries ``declined_reason`` when the absence is a known,
  verified fact rather than a typo (see synapse/registry.py's _DECLINED).
- ``PreconditionUnmet`` — registered, and blocked, with the measurement attached.

MEASUREMENT AND POLICY ARE SEPARATE HERE. ``Observation`` is what a probe measured;
``satisfies_placeholder_policy`` is the rule that turns it into a verdict, and it is named as
a placeholder because slice 1 has no caller entitled to decide what "enough" means.

``match`` over the three plus ``typing.assert_never`` is the enforcement: mypy --strict
fails a caller that forgets a branch. That is a mechanism, not a review convention.

NONE OF THE THREE IS AN EXCEPTION. Both refusals are ordinary states a console renders;
raising would make them indistinguishable from a bug at the call site and turn
availability rendering into try/except control flow.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import ClassVar

from synapse.core.capability import CapabilityDescriptor


class ResolutionStatus(StrEnum):
    """The tag, for rendering and for logs. The TYPE is what callers branch on.

    Present as a ClassVar on each variant rather than a constructor field, so a variant
    cannot be built claiming to be one of the others.
    """

    SATISFIED = "satisfied"
    UNREGISTERED = "unregistered"
    PRECONDITION_UNMET = "precondition_unmet"


@dataclass(frozen=True)
class Observation:
    """What a probe RETURNS: a MEASUREMENT, never a verdict.

    TWO COUNTS, NOT A REDUCED NUMBER, and that is the whole design. A capability whose
    grain is per-series has no single "days of history" — it has one number per series. A
    scalar can only be produced by choosing how to reduce them, and every reduction is a
    POLICY that belongs to whoever is asking:

    - ``MIN`` looks conservative and is unusable. Any real catalogue adds SKUs constantly,
      so one SKU added last week drops the minimum to 7 and blocks the whole store
      permanently — a 5,000-SKU tenant with 4,950 well-covered series would never resolve.
    - ``MAX`` or "any series qualifies" is right for "can I forecast anything" and wrong for
      "can I forecast every SKU".

    So the probe reports how many series it measured and how many clear the threshold, and
    the comparison that turns those into a verdict lives outside it. See
    ``satisfies_placeholder_policy``.

    Deliberately does NOT carry the threshold. The probe is HANDED the declared value by the
    resolution engine and applies it in SQL; it never sources it. So a probe cannot report
    ``required=1`` while the descriptor declares 60 — there is only one place the number
    comes from.
    """

    pairs_measured: int
    pairs_qualifying: int
    measured_at: datetime


@dataclass(frozen=True)
class PreconditionReport:
    """One precondition, evaluated: what was required, what was measured, when.

    FACTS ONLY, NO VERDICT. Whether these numbers amount to "satisfied" is policy and lives
    in ``satisfies_placeholder_policy``, so that the policy is a named thing to argue with
    and delete rather than a comparison buried in a property.

    ALL THE NUMBERS, ALWAYS. "Needs 60 days" on its own tells an operator the capability is
    unavailable without telling them how far away it is. ``pairs_qualifying`` of
    ``pairs_measured`` is what lets a console say "0 of 66 series qualify" instead of
    "blocked", which is the difference between a data problem and a wait.

    ``required`` is ``int`` because the one precondition kind that exists counts days.
    Widening it to a value union is a decision for the second kind.
    """

    name: str
    required: int
    pairs_measured: int
    pairs_qualifying: int
    measured_at: datetime


def satisfies_placeholder_policy(report: PreconditionReport) -> bool:
    """**PLACEHOLDER POLICY FOR SLICE 1.** Deliberately not a considered decision.

    ``pairs_qualifying > 0``. This is not the right rule; it is a rule that READS as a
    placeholder, which ``MIN`` would not have. ``MIN`` would look like a conservative
    engineering choice while quietly being unusable on any growing catalogue, and a wrong
    answer that looks considered is worse than an obvious stub.

    THE TENSION IT DEFERS. "Forecast all SKUs" wants every series to qualify. "Forecast
    anything" wants one. Both are legitimate readings of the same measurement, and neither
    is derivable from the data — the current beta tenant fails under every reduction, so
    nothing here is being tested by reality. The choice needs a CALLER, and the caller
    arrives in slice 2 as the analysis declaration, which supplies both the threshold and
    what to do with the counts.

    DELETE THIS FUNCTION IN SLICE 2 rather than tuning it. It is a named, greppable thing
    precisely so that it cannot survive as an accident.

    (Monotonicity note, which matters for the check-then-fetch gap in ``Satisfied``: THIS
    policy is monotonic — coverage only grows, so ``pairs_qualifying`` only grows. An
    all-series policy would NOT be, because a newly-added SKU raises ``pairs_measured``
    without raising ``pairs_qualifying``. Whoever replaces this must revisit that note.)
    """
    return report.pairs_qualifying > 0


@dataclass(frozen=True)
class Satisfied[RowT]:
    """Resolvable now. Carries a BOUND fetch, not the rows.

    Two-step on purpose. The console's question is "can this tenant have a daily
    series?", and answering it by pulling every row would make availability rendering
    cost a full read. ``fetch`` is the already-bound call; nothing further is decided.

    THE CHECK-THEN-FETCH GAP IS SAFE FOR THIS PRECONDITION KIND AND THIS POLICY ONLY, and
    that is a property of both rather than a general guarantee: history coverage only grows,
    so under ``satisfies_placeholder_policy`` a capability that passed cannot fail by the
    time ``fetch`` runs. Neither half generalises — an all-series policy loses it (a new SKU
    raises pairs_measured without raising pairs_qualifying), and so would a precondition with
    a freshness ceiling. Written down instead of assumed, because slice 2 replaces the policy.
    """

    status: ClassVar[ResolutionStatus] = ResolutionStatus.SATISFIED

    descriptor: CapabilityDescriptor
    fetch: Callable[[], Awaitable[Sequence[RowT]]]


@dataclass(frozen=True)
class Unregistered:
    """No entry under this id.

    ``declined_reason`` is the difference between a mistyped id (``None``) and a
    capability whose absence is a verified fact with a written reason. It is a plain
    string and there is NO descriptor here on purpose: recording why something cannot
    exist must not require declaring a grain and a return shape for rows that do not.
    """

    status: ClassVar[ResolutionStatus] = ResolutionStatus.UNREGISTERED

    capability_id: str
    declined_reason: str | None = None


@dataclass(frozen=True)
class PreconditionUnmet:
    """Registered, and blocked for this scope right now.

    THE OUTCOME A NAIVE REGISTRY LOSES. It carries the descriptor, so a console can
    render what the capability WOULD give — grain, returns, freshness — next to why it
    cannot give it yet.

    ``unmet`` is a tuple, not a single report: a capability may declare more than one
    precondition, and reporting only the first would hide the second the day one
    arrives. All declared preconditions are evaluated, and every unmet one is here.
    """

    status: ClassVar[ResolutionStatus] = ResolutionStatus.PRECONDITION_UNMET

    descriptor: CapabilityDescriptor
    unmet: tuple[PreconditionReport, ...]

    def __post_init__(self) -> None:
        if not self.unmet:
            raise ValueError("PreconditionUnmet with no unmet report is a Satisfied in disguise")
        # Checked against the SAME policy the engine used to select these reports. If the
        # policy changes, this check changes with it — there is no second comparison here to
        # drift out of agreement with the first.
        satisfied = [r.name for r in self.unmet if satisfies_placeholder_policy(r)]
        if satisfied:
            raise ValueError(f"PreconditionUnmet carries a SATISFIED report: {satisfied}")


# Generic in the row type so a caller that knows which capability it asked for keeps its
# types. `resolve()` returns Resolution[object]: a STRING-KEYED registry cannot carry a
# row type, and pretending otherwise with a cast would be a lie in the signature. A
# caller wanting typed rows calls the resolver directly; `resolve()` exists for the
# availability question, which is not row-typed.
type Resolution[RowT] = Satisfied[RowT] | Unregistered | PreconditionUnmet

__all__ = [
    "Observation",
    "PreconditionReport",
    "PreconditionUnmet",
    "Resolution",
    "ResolutionStatus",
    "Satisfied",
    "Unregistered",
    "satisfies_placeholder_policy",
]
