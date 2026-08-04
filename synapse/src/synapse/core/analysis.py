"""THE DEMAND SIDE. What a consumer NEEDS, as data.

Slice 1 built the supply side and nothing else: every field on ``CapabilityDescriptor``
describes what a capability OFFERS. There was no type anywhere for what a consumer REQUIRES —
``resolve()`` took a capability id and keyword arguments, which is an imperative call, not a
declaration. ``MinHistoryDays`` looked like the demand side and was not: it was declared BY a
capability ABOUT ITSELF.

This module is the other half. Nothing here touches a database, constructs SQL or names a
canonical table; import-linter forbids all three to ``synapse.core``.

WHY A DECLARATION AND NOT A FUNCTION. An analysis expressed as code is an analysis whose
requirements can only be discovered by running it. Expressed as data, an operator console can
answer "what would dead_stock need, and can this tenant provide it" without executing
anything — the same reason ``preconditions`` lived on the descriptor rather than inside the
resolver. And adding a second analysis is adding a row, never editing an engine: the rule the
capability registry already follows.

THE THREE THINGS A REQUIREMENT HAS TO SAY, all of which slice 1 could not express:

1. WHICH capability, and which of its ``returns`` this analysis reads. A field the capability
   does not return is a requirement nothing can satisfy, and the registry checks it at import.
2. WHAT THRESHOLD, for each gate the capability declares. This is the parameter that replaced
   ``MinHistoryDays(days=60)`` on the supply side: dead stock wants 90 days of no-sales, a
   forecast wants 60 for seasonality, and both read the same rows.
3. WHAT "ENOUGH" MEANS across a population of series — ``SeriesPolicy``. Only a caller knows
   whether it needs every series or any series, and slice 1's placeholder was standing in for
   this answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

from synapse.core.capability import GateKind
from synapse.core.resolution import SeriesPolicy


@dataclass(frozen=True)
class MinHistoryDays:
    """A BOUND history requirement: this many distinct dates, reduced by this policy.

    MOVED HERE FROM synapse.core.capability, and the move is the point of slice 2. It held a
    value on the SUPPLY side, which works while there is one caller and breaks with two.

    COVERAGE, NOT SPAN. A forecaster needs observations, not calendar distance. A tenant
    onboarded ninety days ago that has sold on twelve of them has a span of 90 and a coverage
    of 12, and only the 12 is a count of things a model can fit to. So ``days`` counts DISTINCT
    dates CARRYING DATA. Span is the rejected alternative, named so the next reader knows it
    was a choice rather than an implementation accident.

    MEASURED PER SERIES, not per tenant, at the capability's declared grain minus its date
    column — enforced at registry import by the grain rule. A per-tenant count would pass
    trivially while saying nothing about whether any individual series is fit.

    A FITNESS requirement, not a computability one. A twelve-day daily series computes
    perfectly well; it is just not the thing a consumer asking for a series means. Resolution
    therefore REFUSES rather than returning a short series, because handing back twelve days to
    a consumer that assumed sixty is the same class of error the ``freshness`` enum prevents.

    ``policy`` IS ON THE GATE, not on the requirement that holds it, and that is structural
    rather than stylistic: a policy is a rule for reducing a PER-SERIES MEASUREMENT, so it only
    means anything where such a measurement exists. A requirement with no gates then has no
    policy field to leave inert or set arbitrarily. If a second gate kind arrives and also
    needs reducing, ``policy`` lifts to something shared — the same "union of one until a
    second is real" discipline as ``GateKind``.
    """

    kind: ClassVar[GateKind] = GateKind.MIN_HISTORY_DAYS

    days: int
    policy: SeriesPolicy

    def __post_init__(self) -> None:
        if self.days < 1:
            raise ValueError(f"min_history_days must be at least 1 day, got {self.days}")


# ONE KIND, and the alias exists so adding a second is a VISIBLE edit here rather than a new
# string flowing through a generic (name, operator, value) triple. Such a triple invented from
# one sample is the guessing this project's contracts keep refusing to do.
type Gate = MinHistoryDays


@dataclass(frozen=True)
class Threshold:
    """A number the ANALYSIS itself uses, distinct from a gate on a capability.

    A gate decides whether a capability may be READ. A threshold is arithmetic the analysis
    performs on rows it has already got — dead stock's ``stale_after_days`` is the second kind:
    no read depends on it, and it is the whole content of the rule.

    ``fitted`` AND ``stands_in_for`` MAKE THE HONESTY A MECHANISM. The standing instruction is
    that thresholds are FITTED from the tenant's own data where possible, and where they are
    not, the constant must name what it stands in for — the ``MinHistoryDays(days=60)`` idiom
    from slice 1, which worked because the comment was there to be read and acted on. A
    comment cannot be enforced; ``__post_init__`` can. So an unfitted threshold that does not
    say what it substitutes for CANNOT BE CONSTRUCTED, and a fitted one must not claim to
    substitute for anything.

    ``days`` rather than a general value type, because both thresholds in existence count days.
    Widening it is a decision for the first one that does not.
    """

    name: str
    days: int
    fitted: bool
    stands_in_for: str | None

    def __post_init__(self) -> None:
        if self.days < 1:
            raise ValueError(f"threshold {self.name!r} must be at least 1 day, got {self.days}")
        if not self.fitted and not self.stands_in_for:
            raise ValueError(
                f"threshold {self.name!r} is a CONSTANT and must name what it stands in for. "
                "A number with no stated derivation is indistinguishable from a number "
                "someone guessed"
            )
        if self.fitted and self.stands_in_for:
            raise ValueError(
                f"threshold {self.name!r} is fitted, so it stands in for nothing; "
                f"remove stands_in_for={self.stands_in_for!r}"
            )


@dataclass(frozen=True)
class CapabilityRequirement:
    """One capability this analysis needs, with the fields it reads and the gates it binds.

    ``fields`` is checked against the capability's ``returns`` at registry import. That check
    is not bureaucracy: it is what would have caught reaching for a field the capability does
    not offer, and reaching for a plausible-but-wrong field is the most likely way an analysis
    goes quietly wrong (see the ``last_source_event_at`` note in
    ``synapse/resolvers/last_sale_at.py``).

    ``gates`` must bind EXACTLY the kinds the capability declares — not a subset. A declared
    gate nobody binds is a gate that never runs, and a gate that never runs is decorative.
    """

    capability_id: str
    fields: tuple[str, ...]
    gates: tuple[Gate, ...]

    def __post_init__(self) -> None:
        if not self.fields:
            raise ValueError(
                f"requirement on {self.capability_id!r} names no fields; an analysis that "
                "reads nothing from a capability does not require it"
            )
        kinds = [gate.kind for gate in self.gates]
        if len(kinds) != len(set(kinds)):
            raise ValueError(f"requirement on {self.capability_id!r} binds a gate kind twice: {kinds}")


@dataclass(frozen=True)
class AnalysisDeclaration:
    """What an analysis declares about itself. Mirrors analysis.schema.json.

    ``grain`` MUST BE CONTAINED IN EVERY REQUIRED CAPABILITY'S GRAIN, checked at registry
    import. That is the composition rule, and it is the first mechanical use of ``grain``
    since it was extracted: an analysis emitting one row per (tenant, store, sku) can only
    join capabilities that identify rows at least that finely. A capability at coarser grain
    cannot be joined without inventing rows, and no amount of care in the analysis body fixes
    a join that was never valid.

    Plain frozen dataclasses rather than Pydantic, for the same reason as
    ``CapabilityDescriptor``: the SCHEMA is the contract and the conformance harness enforces
    it, so a second validating implementation here would be a second source of truth.
    """

    id: str
    version: str
    grain: tuple[str, ...]
    requires: tuple[CapabilityRequirement, ...]
    # What the analysis PRODUCES. Named fields rather than a free-form result, so a consumer
    # can be written against it before anything consumes it — and so the day a scorer arrives
    # it is checkable against this rather than against whatever the code happened to return.
    emits: tuple[str, ...]
    thresholds: tuple[Threshold, ...]

    def __post_init__(self) -> None:
        if not self.requires:
            raise ValueError(f"analysis {self.id!r} requires no capability; it has no inputs")
        ids = [requirement.capability_id for requirement in self.requires]
        if len(ids) != len(set(ids)):
            raise ValueError(f"analysis {self.id!r} requires the same capability twice: {ids}")


DEAD_STOCK = AnalysisDeclaration(
    id="dead_stock",
    version="0.1.0",
    grain=("tenant_id", "store_id", "sku_id"),
    # TWO CAPABILITIES, AND THE COMPOSITION IS FORCED BY THE QUESTION, not chosen to exercise
    # the contract.
    #
    # Dead stock is "no sale in N days" — an ABSENCE. An absence cannot be read from a table
    # of presences: daily_series returns rows ONLY for days that had sales, so a SKU that has
    # never sold produces no rows at all, and the deadest stock in the catalogue is invisible
    # to it. Deriving an absence needs the UNIVERSE of things that could have been present.
    #
    # current_state IS that universe: one row per position that exists. last_sale_at is the
    # presences: one row per position that has ever sold. Dead stock is the difference, and
    # "never sold" is the missing-row case that carries the strongest signal.
    requires=(
        CapabilityRequirement(
            capability_id="current_state",
            # THE UNIVERSE, plus what makes a dead SKU actionable. stock_qty because dead
            # stock with no stock is not a problem to solve, and sku_status because a
            # deliberately delisted SKU is not dead, it is finished.
            fields=("tenant_id", "store_id", "sku_id", "stock_qty", "sku_status"),
            # current_state declares no gates: the hot table either has a row or does not.
            gates=(),
        ),
        CapabilityRequirement(
            capability_id="last_sale_at",
            fields=("tenant_id", "store_id", "sku_id", "last_sale_date"),
            # No gates either, and that is the interesting half: "when did this last sell" is
            # answerable from ONE observation. Dead stock is the one real analysis that works
            # on sparse data precisely because ABSENCE is the signal — it needs no history
            # coverage at all, which is why it is the right first declaration.
            gates=(),
        ),
    ),
    emits=("tenant_id", "store_id", "sku_id", "days_since_last_sale", "is_dead_stock"),
    thresholds=(
        Threshold(
            name="stale_after_days",
            days=90,
            # NOT FITTED, and the constructor forces this to be admitted rather than implied.
            fitted=False,
            stands_in_for=(
                "the tenant's own p90 gap between consecutive sales of the same (store, sku). "
                "90 days is a plausible retail number and nothing more: a fast-moving grocery "
                "SKU is dead at 14 days and a furniture SKU is healthy at 120, so one constant "
                "across a catalogue is wrong for most of it in both directions. The fitted "
                "version is a capability, not arithmetic here, and it is cheap over the "
                "collapsed sale dates: PERCENTILE_CONT(0.9) WITHIN GROUP (ORDER BY gap) over "
                "gap = event_date - LAG(event_date) OVER (PARTITION BY tenant_id, store_id, "
                "sku_id ORDER BY event_date), aggregated per tenant. STILL A CONSTANT, and the "
                "original reason is now spent: it said 'not in the slice that introduces the "
                "declaration', and that slice has landed. The current reason is narrower and "
                "checkable — the fitted version is a CAPABILITY, so it needs a descriptor, a "
                "resolver, a registry row, a contract fixture and a live executability test, "
                "which is the whole shape of a capability slice rather than a threshold change. "
                "Until then this number is wrong for most of a catalogue in both directions and "
                "says so."
            ),
        ),
    ),
)


__all__ = [
    "DEAD_STOCK",
    "AnalysisDeclaration",
    "CapabilityRequirement",
    "Gate",
    "MinHistoryDays",
    "Threshold",
]
