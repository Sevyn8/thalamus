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
``SeriesPolicy`` is the rule that turns it into a verdict, and it is now SUPPLIED BY THE
CALLER rather than assumed. Slice 1 had ``satisfies_placeholder_policy`` because no caller
existed that was entitled to say what "enough" meant across a population of series.

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
from typing import ClassVar, assert_never

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
    the comparison that turns those into a verdict lives outside it, in ``SeriesPolicy``,
    chosen by whoever is asking.

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

    FACTS ONLY, NO VERDICT. Whether these numbers amount to "satisfied" is policy, carried by
    the caller's ``SeriesPolicy`` — so the report is the same object regardless of who is
    asking, and two callers reading the same measurement can legitimately disagree.

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


class SeriesPolicy(StrEnum):
    """What "enough" MEANS across a population of series. Supplied by the caller, never assumed.

    THIS REPLACES ``satisfies_placeholder_policy``, and the distinction matters because the two
    obvious readings of that deletion are not the same:

    - "the placeholder is gone" — TRUE.
    - "ANY stops working" — FALSE. The placeholder's body was ``pairs_qualifying > 0``, which
      IS ``ANY_SERIES``. Deleting it did not remove a behaviour; it promoted that behaviour
      from an UNOWNED DEFAULT to a DECLARED CHOICE. What is gone is the ability to get a
      verdict without saying what you meant.

    Both values are legitimate and neither is derivable from data:

    ``ALL_SERIES`` — every series in scope must clear the threshold. What "forecast every SKU"
    means. Note ``pairs_measured > 0`` is part of it: nought-of-nought is not "all of them
    qualify", it is an empty population, and a policy that returned True there would satisfy a
    tenant with no data at all.

    ``ANY_SERIES`` — one qualifying series is enough. What "forecast anything" means, and what
    a console asking "is this capability usable here at all" means.

    MIN OVER SERIES IS DELIBERATELY NOT A VALUE. It reads as a considered conservative choice
    and is unusable: any growing catalogue adds SKUs constantly, so one SKU added last week
    drops the minimum and blocks the whole store permanently — a 5,000-SKU tenant with 4,950
    well-covered series would never resolve. It is the same rule as ALL_SERIES with a worse
    name, so ALL_SERIES is the honest spelling of it.
    """

    ALL_SERIES = "all_series"
    ANY_SERIES = "any_series"


def satisfies(policy: SeriesPolicy, report: PreconditionReport) -> bool:
    """Apply a caller's policy to a measurement. The ONLY place the two meet.

    ``match`` with ``assert_never``: a third policy value fails mypy --strict here until it is
    handled, rather than silently falling through to a default.
    """
    match policy:
        case SeriesPolicy.ALL_SERIES:
            # pairs_measured > 0 is load-bearing, not defensive — see the class docstring.
            return report.pairs_measured > 0 and report.pairs_qualifying == report.pairs_measured
        case SeriesPolicy.ANY_SERIES:
            return report.pairs_qualifying > 0
        case _:  # pragma: no cover - unreachable while SeriesPolicy has two members
            assert_never(policy)


@dataclass(frozen=True)
class Satisfied[RowT]:
    """Resolvable now. Carries a BOUND fetch, not the rows.

    Two-step on purpose. The console's question is "can this tenant have a daily
    series?", and answering it by pulling every row would make availability rendering
    cost a full read. ``fetch`` is the already-bound call; nothing further is decided.

    THE CHECK-THEN-FETCH WINDOW, AND UNDER ``ALL_SERIES`` NOTHING CLOSES IT.

    Slice 1 flagged that an all-series policy would not be monotonic and that this note would
    need revisiting when such a policy became selectable. It just did, so here is what
    actually happens rather than a warning that it might:

    - Under ``ANY_SERIES`` the window is harmless. Coverage only grows and series are only
      added, so ``pairs_qualifying`` only rises; a capability that satisfied ANY cannot stop
      satisfying it. This is a real property, not an assumption.
    - Under ``ALL_SERIES`` it is not. A new SKU's FIRST SALE raises ``pairs_measured`` without
      raising ``pairs_qualifying``, so a population that satisfied ALL at probe time can fail
      it moments later. One arriving row is enough.

    THE WINDOW IS UNBOUNDED. The probe runs in its own ``rls_session`` transaction and
    ``fetch`` opens another, so there is no shared snapshot; and ``Satisfied`` is an ordinary
    value a caller may hold for as long as it likes before awaiting ``fetch``. So the window
    is not "a few milliseconds", it is "until someone calls fetch".

    NOTHING CLOSES IT, AND THAT IS ACCEPTED FOR NOW. The rows ``fetch`` returns are never
    wrong — they are the same daily-series rows either way. What goes stale is the VERDICT: an
    analysis that declared it needs every series to have 90 days can receive rows covering a
    series with one day, and nothing in this type tells it so.

    THE FIX is for ``Satisfied`` to carry the QUALIFYING POPULATION — the set of series that
    passed — and for ``fetch`` to be narrowed to exactly those, so the answer describes the
    population the verdict was made about. That is a change to what this class holds and to every
    resolver's narrowing.

    RE-DEFERRED, WITH A DIFFERENT AND SELF-TRIGGERING REASON. The old wording said it belonged in
    "a slice with a consumer in it", and a consumer arrived (``resolve_declaration``) without the
    window becoming reachable — because the deferral named a SLICE rather than a CONDITION. Both
    of ``dead_stock``'s requirements declare ``gates=()``, so no population is measured for it and
    this window does not arise at all.

    THE TRIGGER IS: THE FIRST ANALYSIS THAT BINDS A GATE. That is a condition the code can be
    checked against rather than a milestone someone has to remember, which is the whole point —
    a deferral that names its own trigger beats one that names a slice.
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

    ``unmet`` is a tuple, not a single report: a capability may declare more than one gate, and
    reporting only the first would hide the second the day one arrives. Every bound gate is
    evaluated, and every unmet one is here.
    """

    status: ClassVar[ResolutionStatus] = ResolutionStatus.PRECONDITION_UNMET

    descriptor: CapabilityDescriptor
    unmet: tuple[PreconditionReport, ...]

    def __post_init__(self) -> None:
        if not self.unmet:
            raise ValueError("PreconditionUnmet with no unmet report is a Satisfied in disguise")
        # NO POLICY CHECK HERE ANY MORE, and its absence is deliberate rather than an
        # oversight. Slice 1 re-checked every report against the module-level placeholder, so
        # constructing a PreconditionUnmet carrying a satisfied report raised. That check
        # cannot exist now: whether a report is satisfied depends on the CALLER's policy, and
        # this type does not know it — the same report is unmet under ALL_SERIES and satisfied
        # under ANY_SERIES, so there is no policy-free notion of "carries a satisfied report"
        # left to assert. The engine's filter is now the single place the policy is applied
        # (registry.resolve), which is also the only place that knows which policy was asked
        # for. Weaker than slice 1 by exactly the amount the caller gained.


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
    "SeriesPolicy",
    "Unregistered",
    "satisfies",
]
