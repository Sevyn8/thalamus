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
from synapse.core.holdout import Holdout
from synapse.core.provision import Rung
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
    # THE DATE WINDOW THIS REQUIREMENT NEEDS, named as one of the declaration's own thresholds.
    #
    # THE OPERATIONAL HALF OF ``Freshness.AS_OF_DATE``, which has existed since slice 1 to mark
    # capabilities for which a date parameter is meaningful. That was the structural claim; this
    # is what it costs to actually call one. ``resolve_declaration`` reads the named threshold
    # and computes ``date_from``/``date_to`` from the ``as_of`` it is given, because a window is
    # relative to the moment of asking and therefore cannot be a literal in a declaration.
    #
    # DECLARING ONE AGAINST A ``LAST_WRITE`` CAPABILITY IS A CONTRADICTION, and the registry
    # refuses it at import. That refusal is what shows this is the counterpart of an existing
    # contract field rather than a parameter bolted on for one analysis: the freshness enum
    # already says which capabilities a window can mean anything for, and this must agree.
    #
    # None for a capability that takes no window. Both of dead_stock's requirements are.
    window_from_threshold: str | None = None

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
    # THE EXPERIMENT DESIGN, or an explicit None. No default, for the same reason as every other
    # field here: ``None`` is a CLAIM that this analysis produces no actions, and a missing
    # argument is a silence. The registry ties the two together — a declaration with an action
    # proposer MUST have a holdout, because an action without an arm cannot be analysed and a
    # counterfactual cannot be built backwards (see synapse.core.holdout).
    holdout: Holdout | None
    # What the analysis PRODUCES. Named fields rather than a free-form result, and the payoff
    # arrived on schedule: the evaluator's row type is checked against this at registry import,
    # and the action proposer reads these findings rather than whatever the code happened to
    # return. Still declared before a SCORER exists, for the same reason.
    emits: tuple[str, ...]
    thresholds: tuple[Threshold, ...]
    # THE ENVELOPE. The furthest a produced action may travel for ANY tenant — a property of
    # this analysis's maturity, not of any customer, which is precisely why it lives in code
    # where changing it is a reviewed diff rather than an UPDATE.
    #
    # A provision binds a rung; ``synapse.persistence.provision_postgres`` refuses one that
    # exceeds this when it LOADS the row, so an over-privileged provision never reaches an
    # orchestrator. Third instance of declare-in-code / bind-as-data / check-at-the-boundary:
    # capability gate KINDS bound by an analysis, ``emits`` checked against the evaluator, and
    # now this.
    #
    # Defaulted to SHADOW so that a new analysis is not autonomous by omission. An analysis
    # earns a higher ceiling explicitly or does not have one.
    max_rung: Rung = Rung.SHADOW

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
    holdout=Holdout(
        # THE FULL GRAIN: per (tenant, store, sku). Per-STORE would be the cleaner comparison in
        # general and is unusable for the first tenant, which has TWO stores — two units cannot
        # be randomised, any difference measured is a store difference rather than a treatment
        # difference, and half the estate would get no service. The cost of per-SKU is named in
        # Holdout's docstring: it leaks under substitution, which under-measures.
        unit=("tenant_id", "store_id", "sku_id"),
        holdout_percent=20,
        # STABLE AND EXPLICIT. Changing this reshuffles every arm, so it is a deliberate act
        # rather than a side effect of a version bump.
        salt="dead_stock/2026-08",
        fitted=False,
        stands_in_for=(
            "a power calculation, which cannot help here: 66 positions cannot support a "
            "conclusive split at ANY fraction, so 20 is a placeholder for a design that does not "
            "yet have enough subjects to be a design. Concretely, with ONE dead SKU in the "
            "current data a 20% holdout has roughly a one-in-five chance of holding out the only "
            "finding and producing ZERO treated actions. That is not a bug and will be read as "
            "one: it is what underpowered means, and the arithmetic is doing exactly what it "
            "should. The trigger for revisiting is a tenant with enough positions for a split to "
            "mean something — not a calculation someone might run over these 66."
        ),
    ),
    # SHADOW, and it is the default rather than a considered ceiling: dead_stock has never
    # been checked against a human judgement about which SKUs are genuinely dead. Raising this
    # is a reviewed diff, which is the point of it being here rather than in the table.
    max_rung=Rung.SHADOW,
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
        Threshold(
            name="expires_after_days",
            days=30,
            # AN ACTION NEEDS AN EXPIRY because a dead-stock finding decays: the SKU may sell
            # tomorrow, and an action nobody bounded stays on a list forever looking current.
            # Expressed as a Threshold rather than a new mechanism so it inherits the same
            # fitted/stands_in_for constructor discipline.
            fitted=False,
            stands_in_for=(
                "how long a dead-stock finding stays true, which is the same p90 inter-sale gap "
                "that stale_after_days needs and is therefore blocked on the same missing "
                "capability. 30 days is a review cycle, not a measurement: it says 'look at this "
                "within a month' and nothing about when the finding stops holding."
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


STOCKOUT_RISK = AnalysisDeclaration(
    id="stockout_risk",
    version="0.1.0",
    grain=("tenant_id", "store_id", "sku_id"),
    # THE COMPLEMENT OF dead_stock, and chosen for that rather than for being impressive. A SKU
    # cannot be both dead and about to run out, so the two analyses partition the catalogue and
    # neither needs a precedence rule against the other. Overstock would have been dead_stock's
    # claim at a different severity, with both proposing REVIEW on the same targets and nothing
    # in the action contract to adjudicate.
    requires=(
        CapabilityRequirement(
            capability_id="current_state",
            # stock_qty is the numerator. sku_status because a delisted SKU running out is the
            # intended end of its life, not a problem.
            fields=("tenant_id", "store_id", "sku_id", "stock_qty", "sku_status"),
            gates=(),
        ),
        CapabilityRequirement(
            capability_id="daily_series",
            fields=("tenant_id", "store_id", "sku_id", "event_date", "net_quantity"),
            # The rate is computed over a TRAILING window, not the tenant's whole history: a
            # rate over eighty days containing a promotion describes a period that has ended,
            # and cover is a forward-looking statement. Named rather than inlined so the
            # declaration stays the single source of the number.
            window_from_threshold="window_days",
            # THE FIRST GATE ANY ANALYSIS HAS EVER BOUND. daily_series has declared
            # MIN_HISTORY_DAYS since slice 1 and nothing bound it, because dead_stock composes
            # two gateless capabilities — so the entire precondition path was unexercised by a
            # real analysis until now.
            #
            # SEVEN, FROM THE MEASURED LADDER, not from taste. Against staging's 613 events:
            # 1 day -> 65/65, 3 -> 61, 5 -> 55, 7 -> 46, 10 -> 25, 14 -> 9, 20 -> 0, 60 -> 0.
            # Seven passes 46 of 65 and refuses 19, so both directions of the precondition path
            # are exercised by real data rather than only by tests. It is also the point at which
            # a daily rate stops being one week of noise.
            #
            # DO NOT MOVE THIS TO MAKE ANYTHING PASS. If it stops splitting, that is a finding
            # about the data, not a reason to lower the bar.
            #
            # ANY_SERIES, AND THAT CHOICE IS WHAT DISCHARGED SLICE 2's DEFERRAL. ALL_SERIES with
            # 46/65 gives PreconditionUnmet and the analysis never runs at all. ANY_SERIES is
            # satisfied — and before slice 7, fetch would then have returned rows for all 65
            # INCLUDING the 19 that failed, so the analysis would have computed cover for series
            # it had just declared unfit. Satisfied now carries the qualifying population and the
            # narrowing is bound into fetch.
            gates=(MinHistoryDays(days=7, policy=SeriesPolicy.ANY_SERIES),),
        ),
    ),
    emits=(
        "tenant_id",
        "store_id",
        "sku_id",
        "days_of_cover",
        "is_at_risk",
        # DECLARED OUTPUT, not a log line. Four conditions make a position unassessable, and a
        # consumer must be able to tell "no risk" from "not assessed" — an absence cannot say
        # which. The registry checks this against StockoutRiskRow's fields at import.
        "refused_because",
    ),
    holdout=Holdout(
        unit=("tenant_id", "store_id", "sku_id"),
        holdout_percent=20,
        # INDEPENDENT OF dead_stock's SALT, deliberately. Correlated arms across concurrent
        # experiments reduce power for both, so each analysis randomises separately.
        #
        # THE CONSEQUENCE, RECORDED HERE BECAUSE THE PERSON IT AFFECTS IS DOING AN ATTRIBUTION
        # STUDY AND WILL READ THIS FIRST. Independent assignment means one SKU can be dead_stock
        # HOLDOUT and stockout_risk TREATMENT at the same time. In shadow that is harmless:
        # nothing is delivered, so a "holdout" SKU receives nothing and contaminates nothing.
        #
        # The moment ANY analysis leaves shadow, it stops being harmless. A dead_stock holdout
        # SKU that receives a stockout_risk action is no longer a clean control, and dead_stock's
        # attribution degrades in a way ITS OWN NUMBERS CANNOT SHOW — the contamination lives in
        # a different analysis's log. Nothing here detects it.
        #
        # THE TRIGGER IS: THE FIRST ANALYSIS TO LEAVE SHADOW. Not this slice. The options at that
        # point are a shared salt (correlated arms, one experiment), a global per-SKU suppression
        # when any analysis holds it out, or accepting the contamination and bounding it — and
        # picking between them needs a real delivery mechanism to reason about.
        salt="stockout_risk/2026-08",
        fitted=False,
        stands_in_for=(
            "a power calculation, exactly as dead_stock's does and for the same reason: 65 "
            "series cannot support a conclusive split at any fraction. 20 matches dead_stock so "
            "the two are comparable, which is worth more than either number being right."
        ),
    ),
    max_rung=Rung.SHADOW,
    thresholds=(
        Threshold(
            name="window_days",
            days=28,
            fitted=False,
            stands_in_for=(
                "the window length at which this tenant's demand rate is most predictive, which "
                "would be fitted by backtesting rate-from-window-N against realised demand — "
                "infrastructure that does not exist. 28 is defensible beyond convention though: "
                "it is FOUR COMPLETE WEEKLY CYCLES, so day-of-week effects average out instead "
                "of dominating. Seven or fourteen days is one or two cycles and carries the "
                "week's shape as if it were the trend; sixty or more describes a period that has "
                "ended. The fitted version needs realised-demand comparison, not arithmetic."
            ),
        ),
        Threshold(
            name="at_risk_below_days",
            days=14,
            fitted=False,
            stands_in_for=(
                "the replenishment LEAD TIME, and this one is pure convention — fourteen days is "
                "a common retail reorder horizon and nothing more. Three verified facts make the "
                "correct number unknowable here. (1) lead_time_distribution is in the registry's "
                "_DECLINED with a written reason: no observed lead times exist anywhere in "
                "canonical, because a distribution needs paired order-issue and receipt events "
                "and nothing produces either. (2) the canonical hot table DOES "
                "carry lead_time_days SMALLINT NULL, but dis_validation.provenance classifies it "
                "MAPPING-PRODUCED — whatever a source asserted, not a measurement — so it could "
                "not stand in for an observed lead time even if populated. (3) It is not in "
                "current_state's `returns` and the resolver does not project it, so Synapse "
                "cannot read it at all today; using it would mean widening the capability. "
                "UNVERIFIED, because staging is private-IP only and was not reachable when this "
                "was written: whether the column actually holds values for this tenant. If it "
                "does, this threshold becomes derivable per SKU and stops being a constant. "
                "Check it by counting rows where lead_time_days IS NOT NULL on the canonical hot "
                "table — the one synapse/resolvers/current_state.py names — under the PLATFORM "
                "GUC, since that table is FORCE RLS and a bare count reads zero for everyone."
            ),
        ),
        Threshold(
            name="stale_after_days",
            days=3,
            fitted=False,
            stands_in_for=(
                "this tenant's actual ingestion cadence — how often data really arrives — which "
                "telemetry.connector_health was built to answer and cannot: its missed_intervals "
                "column is NULL in Phase A because config.sources.schedule is a free-text human "
                "label rather than a machine cadence. Three days says a rate should not be more "
                "than a few days behind the stock it is divided into, when the decision horizon "
                "is fourteen. NOTE that on today's data every series is seventeen days stale, so "
                "EVERY position is refused and the analysis produces nothing. That is the guard "
                "working, the same way '0 of 65 have 60 days' was the correct answer; it is not "
                "a reason to loosen this."
            ),
        ),
        Threshold(
            name="expires_after_days",
            days=7,
            fitted=False,
            stands_in_for=(
                "how long a cover estimate stays true, which decays with the same unknown lead "
                "time as at_risk_below_days. Seven is half the decision horizon: advice that "
                "something may run out within fourteen days is not worth acting on when it is "
                "already a fortnight old. Shorter than dead_stock's thirty because a stockout "
                "estimate decays faster than an absence does."
            ),
        ),
    ),
)
