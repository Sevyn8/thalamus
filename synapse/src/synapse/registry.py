"""The capability registry, the analysis declarations, and the resolution engine. ALL DATA.

FOUR MAPPINGS AND TWO FUNCTIONS, and which reads which matters:

- ``_REGISTRY``     capability id -> descriptor + resolver + gate probes.
- ``_DECLINED``     capability ids that will never have an entry, and the verified reason.
- ``_DECLARATIONS`` analysis id -> its declaration.
- ``_ANALYSES``     analysis id -> its evaluator function.

``resolve()`` reads ``_REGISTRY`` and ``_DECLINED`` and returns one of the three outcomes in
``synapse.core.resolution``. ``resolve_declaration()`` reads ``_DECLARATIONS``, calls
``resolve()`` once per requirement, and returns one of the three in
``synapse.core.declaration_resolution``. ``_ANALYSES`` is read by the import-time checks and by
whoever evaluates; nothing here calls an evaluator, because resolution and arithmetic are
separate concerns.

(The previous version of this paragraph said "``resolve()`` reads them", of all three mappings.
That was FALSE when written — resolve() never touched ``_DECLARATIONS`` — and slice 3 adding
``resolve_declaration()`` would have made it quietly true, which is worse than leaving it wrong:
the drift that exposes a false claim never happens, and a grep for expired claims never fires
because by then it is accurate. Corrected by naming each reader explicitly.)

There is no dispatch on capability id or analysis id anywhere — adding either is adding a row,
and every invariant below is checked at import rather than trusted.

DECLARATIONS LIVE HERE RATHER THAN IN THEIR OWN MODULE because the checks that matter are
CROSS-checks: an analysis's fields against a capability's ``returns``, its grain against every
required capability's grain, its gates against what each capability declares. Those need both
sides in scope, and a separate module would either duplicate the registry import or invert the
layering. The name stays "registry" for both.

WHERE THIS SITS IN THE LAYERING. Above the resolvers, not beside them: the registry must
import resolvers to bind them, so ``synapse.registry`` is the top layer, ``synapse.resolvers``
is the middle, and ``synapse.core`` is the pure bottom. That order is an import-linter
``layers`` contract in dis/pyproject.toml, so core cannot import upward and a resolver
cannot reach back into the registry. This module names no table and constructs no SQL —
``AsyncEngine`` is a parameter type and nothing more, and the table-name containment test
covers this file like every other module outside ``synapse/resolvers/``.

WHAT IS DELIBERATELY NOT HERE. Keying is by id ALONE, with the version on the descriptor.
Two capabilities at one version each cannot justify a design for multiple versions
coexisting under one id, and inventing the resolution rules for that from zero samples is
the guessing this project's contracts keep refusing to do.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from types import MappingProxyType
from typing import Final, Protocol, assert_never
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from synapse.core.action import Action
from synapse.core.analysis import (
    DEAD_STOCK,
    STOCKOUT_RISK,
    AnalysisDeclaration,
    Gate,
    MinHistoryDays,
)
from synapse.core.capability import (
    CURRENT_STATE,
    DAILY_SERIES,
    LAST_SALE_AT,
    CapabilityDescriptor,
    CapabilityScope,
    Freshness,
    GateKind,
)
from synapse.core.dead_stock import DeadStockRow, evaluate_dead_stock
from synapse.core.dead_stock_actions import propose_dead_stock_actions
from synapse.core.declaration_resolution import (
    DeclarationBlocked,
    DeclarationResolution,
    DeclarationSatisfied,
    DeclarationUndeclared,
)
from synapse.core.provision import Rung
from synapse.core.refusal import RefusalReason, counts_by_reason
from synapse.core.resolution import (
    Observation,
    PreconditionReport,
    PreconditionUnmet,
    Resolution,
    Satisfied,
    SeriesPolicy,
    Unregistered,
    satisfies,
)
from synapse.core.stockout_actions import propose_stockout_actions
from synapse.core.stockout_risk import StockoutRiskRow, evaluate_stockout_risk
from synapse.resolvers.current_state import resolve_current_state
from synapse.resolvers.daily_series import (
    DATE_COLUMN,
    SERIES_GRAIN,
    probe_min_history_days,
    resolve_daily_series,
)
from synapse.resolvers.last_sale_at import resolve_last_sale_at

# A resolver takes the engine and the scope, plus whatever narrowing IT declares. The
# ellipsis is honest: signatures differ (daily_series requires a date window,
# current_state has no concept of one) and flattening them into one shape would mean
# inventing a shared parameter object for two samples.
Resolver = Callable[..., Awaitable[Sequence[object]]]

# An analysis evaluator: pure, synchronous, rows in and rows out. NOT async and NOT engine-taking,
# and both are deliberate — an evaluator that could reach a database would be a resolver wearing
# the wrong name, and the whole point of the split is that arithmetic happens on rows somebody
# else fetched.
Evaluator = Callable[..., Sequence[object]]

# An action proposer: pure, synchronous, findings in and actions out. Same shape as an evaluator
# and for the same reasons — a proposer that could reach a database would be a resolver wearing
# the wrong name.
Proposer = Callable[..., Sequence[Action]]

# A PLAN: the adapter that knows ONE analysis's call signatures. Given a resolved declaration
# and a slot date, it awaits whatever fetches that analysis needs, calls its evaluator and its
# proposer with their own arguments, and returns actions.
#
# WHY THIS EXISTS RATHER THAN THE ORCHESTRATOR CALLING evaluate/propose DIRECTLY. Evaluator and
# Proposer are deliberately typed with an ellipsis because their signatures DIFFER — dead_stock's
# evaluator takes (universe, selling, stale_after_days, as_of) and nothing says the next one
# will. An orchestrator that called them directly would have to know each analysis's arguments,
# which is analysis-specific knowledge in a component whose whole point is to be generic. So the
# knowledge stays with the analysis and the orchestrator sees ONE uniform shape.
#
# FOURTH INSTANCE OF THE PLUGIN PATTERN, not a new mechanism: descriptor+resolver,
# declaration+evaluator, declaration+proposer, and now declaration+plan.


@dataclass(frozen=True)
class PlanResult:
    """What one analysis produced for one slot: its actions, and what it could not assess.

    WHY THE RETURN WIDENED FROM ``Sequence[Action]``. Refusals produce NO ACTIONS by definition —
    a refusal is the absence of a verdict — so a return type of actions alone can express
    "nothing found" and cannot express "nothing could be assessed". Those are different facts and
    an operator needs them apart: the first is a quiet catalogue, the second is broken input.
    ``synapse.run`` recorded only counts, so the console had to render a third state meaning
    "zero, and we cannot tell which". This is what removes that ambiguity at the source.

    THREE ALTERNATIVES WERE CLOSED before widening a shared signature. The refusals cannot ride
    on the actions (there are none); they cannot be stashed on the resolution
    (``DeclarationSatisfied`` is frozen); and the plan cannot write them itself without the
    registry reaching a database, which an import-linter contract forbids by name. Re-deriving
    them in the orchestrator would mean fetching and evaluating twice.

    ``refusals`` IS KEYED BY A CLOSED VOCABULARY, never free text — the keys are stored, and a
    stored key that varies per slot breaks the re-run stability ``synapse.run`` depends on.

    EVERY ANALYSIS CAN NOW REFUSE. This used to read "Empty for an analysis that cannot refuse
    (dead_stock) and for a run that refused nothing; those two are deliberately indistinguishable
    here" was true when dead_stock had no refusal concept, and is false since it gained one. An empty
    map now means one thing: this run refused nothing. Anything reading it as "this analysis
    cannot refuse" is reading a distinction that no longer exists.
    """

    actions: Sequence[Action]
    refusals: Mapping[RefusalReason, int] = field(default_factory=dict)


Plan = Callable[[DeclarationSatisfied, date], Awaitable[PlanResult]]

# The dataclass each declaration's evaluator returns, for the emits check below. A mapping rather
# than an attribute on the evaluator, because a plain function cannot carry one without either a
# decorator or a mutated __dict__, and both hide the binding from the reader.
_EVALUATOR_ROWS: Final[Mapping[str, type]] = MappingProxyType(
    {
        DEAD_STOCK.id: DeadStockRow,
        STOCKOUT_RISK.id: StockoutRiskRow,
    }
)


class Probe(Protocol):
    """Measures one precondition for one scope. Returns a measurement, never a verdict.

    A Protocol rather than a ``Callable[...]`` alias so the parameters can be
    KEYWORD-EXPLICIT. Positional would have made ``store_id`` and ``sku_id`` — both
    optional, adjacent, and easy to transpose — a silent hazard, and a transposed narrowing
    would measure the wrong series rather than fail.

    ``sku_id`` IS HERE, and its absence was the second half of the per-tenant defect: the
    earlier signature accepted ``store_id`` only, so a probe could not be asked about a
    single series even in principle. The question was structurally unaskable, not merely
    unasked.

    ``required`` is HANDED IN, from the descriptor, by the resolution engine. A probe never
    sources a threshold, so it cannot report one that differs from the declaration; it
    applies the number it is given, in SQL, and returns counts.
    """

    async def __call__(
        self,
        engine: AsyncEngine,
        scope: CapabilityScope,
        *,
        store_id: UUID | None = None,
        sku_id: str | None = None,
        required: int,
    ) -> Observation: ...


@dataclass(frozen=True)
class ProbeBinding:
    """A probe, plus the GRAIN IT MEASURES AT, declared so it can be checked.

    THE GRAIN RULE (enforced in ``_check_registry``): a precondition must be measured at the
    capability's declared grain MINUS the date column. ``series_grain | {date_column}`` must
    equal ``descriptor.grain`` exactly.

    WHY IT IS A REGISTRY-LEVEL RULE AND NOT A COMMENT IN ONE RESOLVER. ``daily_series``
    declares grain ``(tenant_id, store_id, sku_id, event_date)`` and its first probe measured
    at ``(tenant_id)`` — one number for the whole tenant, passing a 60-day threshold on data
    where every individual series had ~9 observations. Two artifacts in the same slice
    disagreed about what the capability was about, and neither could see the other because
    the measured grain existed only as a WHERE clause. Declaring it as data makes the
    disagreement mechanically detectable, and it is the ONE finding from that defect that
    generalises: every future capability with a precondition is subject to the same check
    without anyone remembering to apply it.
    """

    measure: Probe
    series_grain: tuple[str, ...]
    date_column: str


@dataclass(frozen=True)
class RegisteredCapability:
    """One registry row: what it declares, what resolves it, what measures its gates.

    ``probes`` is keyed BY PRECONDITION NAME rather than being a bare tuple, which is what
    makes the pairing checkable without a database: a declared precondition with no probe
    would otherwise be a gate that always passes — a guard that protects nothing, which is
    the failure mode this repo has already hit twice with vacuously-passing checks.
    """

    descriptor: CapabilityDescriptor
    resolver: Resolver
    probes: Mapping[GateKind, ProbeBinding]


_REGISTRY: Final[Mapping[str, RegisteredCapability]] = MappingProxyType(
    {
        CURRENT_STATE.id: RegisteredCapability(
            descriptor=CURRENT_STATE,
            resolver=resolve_current_state,
            # No gates, so no probes. Verified-empty on both sides.
            probes=MappingProxyType({}),
        ),
        DAILY_SERIES.id: RegisteredCapability(
            descriptor=DAILY_SERIES,
            resolver=resolve_daily_series,
            probes=MappingProxyType(
                {
                    GateKind.MIN_HISTORY_DAYS: ProbeBinding(
                        measure=probe_min_history_days,
                        # Imported from the resolver, NOT retyped here. The constants are the
                        # ones the probe's own GROUP BY is built from, so this binding cannot
                        # declare a grain the query does not implement.
                        series_grain=SERIES_GRAIN,
                        date_column=DATE_COLUMN,
                    )
                }
            ),
        ),
        LAST_SALE_AT.id: RegisteredCapability(
            descriptor=LAST_SALE_AT,
            resolver=resolve_last_sale_at,
            # No gates, so no probes. Verified-empty on both sides: "when did this last sell"
            # is answerable from one observation.
            probes=MappingProxyType({}),
        ),
    }
)


# THE ANALYSIS DECLARATIONS. Data, exactly like _REGISTRY: adding an analysis is adding a row
# here, never editing an engine. Their output is consumed by an evaluator and, from slice 4, by
# an action proposer; nothing SCHEDULES a run or DELIVERS a result anywhere, which is why the
# declaration still has no schedule and no destination.
_DECLARATIONS: Final[Mapping[str, AnalysisDeclaration]] = MappingProxyType(
    {
        DEAD_STOCK.id: DEAD_STOCK,
        STOCKOUT_RISK.id: STOCKOUT_RISK,
    }
)


# THE EVALUATORS. Data binding an id to a function, exactly as _REGISTRY binds a capability id
# to a resolver — the plugin shape, not an engine. Adding an analysis is a _DECLARATIONS row
# plus an _ANALYSES row plus a function, and no code here changes.
#
# Typed loosely for the same reason Resolver is: signatures differ by what each analysis reads,
# and flattening them into one shape would mean inventing a shared parameter object from one
# sample. The import-time check below is what keeps a binding honest — it compares the
# evaluator's OUTPUT FIELDS against the declaration's `emits`, so the declaration's promise about
# what it produces is verified against what the code produces.
_ANALYSES: Final[Mapping[str, Evaluator]] = MappingProxyType(
    {
        DEAD_STOCK.id: evaluate_dead_stock,
        STOCKOUT_RISK.id: evaluate_stockout_risk,
    }
)


# THE ACTION PROPOSERS. Third instance of the plugin shape: descriptor+resolver,
# declaration+evaluator, declaration+proposer. A declaration may legitimately have no proposer —
# an analysis whose findings nobody acts on yet — so this is a SUBSET of _DECLARATIONS rather
# than a parallel of it, and the checks below enforce the direction that matters: a proposer with
# no declaration is arithmetic nothing describes, and a declaration WITH a proposer must carry a
# holdout because an action without an arm can never be analysed.
_ACTIONS: Final[Mapping[str, Proposer]] = MappingProxyType(
    {
        DEAD_STOCK.id: propose_dead_stock_actions,
        STOCKOUT_RISK.id: propose_stockout_actions,
    }
)


# THE PLANS. One per analysis that proposes actions, binding an id to the adapter that knows
# that analysis's own call signatures. See the Plan alias for why this indirection exists.
#
# A plan is where the two-capability composition actually HAPPENS at runtime: it awaits both
# fetches, hands them to the evaluator in the order that evaluator expects, and passes the
# declaration and capability versions through to the proposer so provenance is complete. Nothing
# in here decides anything analytical — every threshold and every version comes from the
# declaration and the resolution.
async def _plan_dead_stock(satisfied: DeclarationSatisfied, as_of: date) -> PlanResult:
    """Fetch, evaluate and propose for dead_stock. The gateless one: no window, no narrowing.

    IT REFUSES NOW, AND THIS DOCSTRING USED TO SAY IT COULD NOT. The previous version read "NO
    REFUSALS, AND NOT BECAUSE NONE HAPPENED. dead_stock cannot refuse at all", and a comment in
    the console's primitives.tsx was built on that sentence. Both were true until the evaluator
    gained the declaration's own stock premise and a feed-freshness check; both are corrected in
    the same commit, because a stale claim about a refusal concept is exactly what makes an empty
    breakdown unreadable.

    ``feed_stale_after_days`` IS READ OFF THE DECLARATION BY NAME, like the other two, so a
    rename fails loudly here rather than silently producing an unrefused run. It is deliberately
    NOT called ``stale_after_days``: the thresholds mapping is name-keyed, so a collision would
    overwrite the 90-day rule with the 3-day one and nothing would report it. AnalysisDeclaration
    refuses a duplicate name outright; this is the second layer.

    THE REFUSALS ARE COUNTED HERE, from the findings, exactly as _plan_stockout_risk does. This
    is the only scope that holds them: the proposer takes findings and returns actions, so a
    caller downstream of it cannot recover what was refused.
    """
    universe = await satisfied.fetches["current_state"]()
    selling = await satisfied.fetches["last_sale_at"]()
    thresholds = {threshold.name: threshold.days for threshold in satisfied.declaration.thresholds}
    findings = evaluate_dead_stock(
        universe,  # type: ignore[arg-type]
        selling,  # type: ignore[arg-type]
        stale_after_days=thresholds["stale_after_days"],
        feed_stale_after_days=thresholds["feed_stale_after_days"],
        as_of=as_of,
    )
    return PlanResult(
        actions=propose_dead_stock_actions(
            findings,
            universe,  # type: ignore[arg-type]
            declaration=satisfied.declaration,
            capability_versions=satisfied.capability_versions,
            as_of=as_of,
        ),
        refusals=counts_by_reason(findings),
    )


async def _plan_stockout_risk(satisfied: DeclarationSatisfied, as_of: date) -> PlanResult:
    """Fetch, evaluate and propose for stockout_risk.

    ``min_observations`` IS READ OFF THE GATE, not restated. The evaluator's in-window
    sufficiency check must use the same number the gate used, or the two would drift into
    disagreeing about what "enough history" means — the gate over all history, the evaluator
    over the window, but the same bar.
    """
    universe = await satisfied.fetches["current_state"]()
    series = await satisfied.fetches["daily_series"]()
    thresholds = {threshold.name: threshold.days for threshold in satisfied.declaration.thresholds}
    requirement = next(r for r in satisfied.declaration.requires if r.capability_id == "daily_series")
    (gate,) = requirement.gates

    findings = evaluate_stockout_risk(
        universe,  # type: ignore[arg-type]
        series,  # type: ignore[arg-type]
        window_days=thresholds["window_days"],
        at_risk_below_days=thresholds["at_risk_below_days"],
        stale_after_days=thresholds["stale_after_days"],
        min_observations=gate.days,
        as_of=as_of,
    )
    # THE REFUSALS ARE COUNTED HERE AND NOWHERE ELSE. This is the only scope that holds the
    # findings: the proposer takes them and returns actions, and a refused position produces no
    # action, so a caller downstream of the proposer cannot recover what was refused. Before this
    # returned them, the counts were computed by an integration test's print and discarded.
    return PlanResult(
        actions=propose_stockout_actions(
            findings,
            universe,  # type: ignore[arg-type]
            declaration=satisfied.declaration,
            capability_versions=satisfied.capability_versions,
            as_of=as_of,
        ),
        refusals=counts_by_reason(findings),
    )


_PLANS: Final[Mapping[str, Plan]] = MappingProxyType(
    {
        DEAD_STOCK.id: _plan_dead_stock,
        STOCKOUT_RISK.id: _plan_stockout_risk,
    }
)


# IDS THAT WILL NOT GET AN ENTRY, and the verified reason. A plain string: no grain, no
# returns, no freshness, no version. That is the point — recording why something cannot
# exist must not require declaring a row shape for rows nobody has ever produced, which is
# how a registry starts describing behaviour it does not have.
#
# The alternative was registering these as capabilities that report their own
# unavailability. Rejected: a descriptor is a claim about a shape, and a claim about a
# shape that has never been produced is the artifact class this project keeps unpicking.
_DECLINED: Final[Mapping[str, str]] = MappingProxyType(
    {
        "lead_time_distribution": (
            "No observed lead times exist in canonical, so no distribution can be computed. "
            "The hot table's lead_time_days column is a MAPPING-PRODUCED declared scalar "
            "(dis_validation.provenance classifies it so) — whatever a source asserts, not a "
            "measurement. A distribution needs paired order-issue and receipt events: the "
            "change-events table admits a RECEIPT subtype in its open vocabulary, but nothing "
            "in the repository produces one (verified by grep across services, libs, mappings "
            "and connectors) and no order-issue event exists at all. Building this over "
            "lead_time_days would report a source's claim as an observed distribution."
        ),
    }
)


def _bound(gate: Gate) -> tuple[GateKind, int, SeriesPolicy]:
    """A caller's bound gate, unpacked as (kind, threshold, policy).

    ``match`` over a union of one, with ``assert_never``: adding a second gate kind fails mypy
    --strict here until it is handled, which is the visible edit the ``Gate`` union alias in
    synapse.core.analysis exists to force.

    ALL THREE COME FROM THE CALLER. Slice 1 read the threshold off the DESCRIPTOR and applied a
    module-level policy; both now arrive bound together on the gate, so a capability cannot
    dictate either and a caller cannot supply one without the other.
    """
    match gate:
        case MinHistoryDays(days=days, policy=policy):
            return MinHistoryDays.kind, days, policy
        case _:  # pragma: no cover - unreachable while Gate has one member
            assert_never(gate)


def _check_registry() -> None:
    """Registry invariants, checked at IMPORT because a broken one fails silently.

    Four of them, and each has a specific silent failure it prevents:

    - key equals ``descriptor.id`` — otherwise a lookup by the descriptor's own id misses,
      and the capability reports as unregistered while sitting in the registry.
    - probes are exactly the declared gate kinds — a declared gate with no probe is a gate that
      cannot be measured, and a probe with no declared gate is a measurement nothing consults.
    - THE GRAIN RULE: every probe measures at the capability's declared grain minus the date
      column. A probe measuring coarser answers a different question and passes trivially —
      the per-tenant defect. See ``ProbeBinding``.
    - no id is both registered and declined — the two mappings would give contradictory
      answers depending on which is consulted first.

    AT IMPORT, not in a test, and that distinction matters in THIS repo: there is no CI, so a
    check that only a test performs is a check that runs when someone remembers to run
    ``make test``. This one runs the first time anything imports the registry.
    """
    for key, entry in _REGISTRY.items():
        if key != entry.descriptor.id:
            raise ValueError(f"registry key {key!r} does not match descriptor id {entry.descriptor.id!r}")
        declared = set(entry.descriptor.gates)
        if declared != set(entry.probes):
            raise ValueError(
                f"{key!r} declares gates {sorted(declared)} but registers probes "
                f"{sorted(entry.probes)}; a declared gate with no probe cannot be measured"
            )
        for name, binding in entry.probes.items():
            _check_probe_grain(key, name, binding, entry.descriptor)
    overlap = sorted(set(_REGISTRY) & set(_DECLINED))
    if overlap:
        raise ValueError(f"{overlap} are both registered and declined")


def _check_probe_grain(
    capability_id: str,
    precondition_name: str,
    binding: ProbeBinding,
    descriptor: CapabilityDescriptor,
) -> None:
    """THE GRAIN RULE. A precondition is measured at the declared grain minus the date column.

    Three assertions, because the equality alone can be satisfied wrongly:

    1. ``series_grain | {date_column} == set(descriptor.grain)`` — the measurement covers the
       capability's identity exactly. Measuring COARSER is the defect this exists for: a
       ``(tenant_id)`` measurement against a ``(tenant_id, store_id, sku_id, event_date)``
       grain passes any threshold the tenant's calendar can reach while telling you nothing
       about a single series. Measuring FINER is equally wrong in the other direction — it
       would gate on a grain the capability never returns.
    2. ``date_column`` is IN the declared grain — otherwise the exclusion is excluding nothing
       and the equality above could hold with an invented column name.
    3. ``date_column`` is NOT in ``series_grain`` — grouping by the date makes every group one
       date and every coverage 1, which is a measurement that always fails rather than always
       passes. Wrong in the safe direction is still wrong.
    """
    covered = set(binding.series_grain) | {binding.date_column}
    grain = set(descriptor.grain)
    if binding.date_column not in grain:
        raise ValueError(
            f"{capability_id!r} probe {precondition_name!r} excludes date column "
            f"{binding.date_column!r}, which is not in the declared grain {sorted(grain)} — "
            "so the exclusion excludes nothing"
        )
    if binding.date_column in binding.series_grain:
        raise ValueError(
            f"{capability_id!r} probe {precondition_name!r} groups BY its date column "
            f"{binding.date_column!r}; every group would be one date and every coverage 1"
        )
    if covered != grain:
        raise ValueError(
            f"{capability_id!r} probe {precondition_name!r} measures at "
            f"{sorted(binding.series_grain)} + {binding.date_column!r}, but the capability's "
            f"declared grain is {sorted(grain)}. A precondition must be measured at the "
            "declared grain minus the date column: measuring coarser answers a different "
            "question and passes trivially"
        )


def _check_declarations() -> None:
    """Analysis declaration invariants, checked at IMPORT alongside the registry's.

    FOUR CROSS-CHECKS, each catching something a declaration cannot catch about itself:

    - key equals ``declaration.id``, for the same reason as the capability registry.
    - every required capability is REGISTERED. A requirement naming a capability that does not
      exist is a declaration that can never resolve, and an analysis that can never resolve is
      the artifact class this project keeps deleting. A DECLINED capability fails here too, with
      its recorded reason attached — that is the most useful possible error message for someone
      who has just written a requirement for something known impossible.
    - THE COMPOSITION RULE: the analysis's grain must be CONTAINED IN every required
      capability's grain. This is the first mechanical use of ``grain`` since it was extracted
      from one resolver, and it is why that extraction was right: an analysis emitting one row
      per (tenant, store, sku) can only join capabilities that identify rows at least that
      finely. A capability at coarser grain cannot be joined without inventing rows, and no
      amount of care in the analysis body fixes a join that was never valid.
    - every required FIELD is in that capability's ``returns``. This is the check that would
      catch reaching for a plausible-but-absent field — the most likely way an analysis goes
      quietly wrong.

    FIVE OF THEM NOW; the last two arrived with the evaluators.

    Gate BINDING is checked at resolve() rather than here, and that is still right even though
    ``resolve_declaration()`` now supplies a declaration's gates AS the binding on the call. The
    check belongs where the call is made because a declaration may legitimately be written
    before the capability grows a gate — and when that happens the declaration is not wrong, it
    is out of date, and the loud failure should come from the attempt rather than from import.
    A declaration that binds nothing against a capability that later declares a gate fails at
    resolve() with the exact mismatch named. See ``resolve``.
    """
    for key, declaration in _DECLARATIONS.items():
        if key != declaration.id:
            raise ValueError(f"declaration key {key!r} does not match analysis id {declaration.id!r}")
        for requirement in declaration.requires:
            entry = _REGISTRY.get(requirement.capability_id)
            if entry is None:
                declined = _DECLINED.get(requirement.capability_id)
                because = f" It is DECLINED: {declined}" if declined else ""
                raise ValueError(
                    f"analysis {key!r} requires capability {requirement.capability_id!r}, "
                    f"which is not registered.{because}"
                )
            descriptor = entry.descriptor
            missing_grain = sorted(set(declaration.grain) - set(descriptor.grain))
            if missing_grain:
                raise ValueError(
                    f"analysis {key!r} emits at grain {sorted(declaration.grain)} but requires "
                    f"{requirement.capability_id!r}, whose grain {sorted(descriptor.grain)} does "
                    f"not contain {missing_grain}. A coarser capability cannot be joined at a "
                    "finer grain without inventing rows"
                )
            missing_fields = sorted(set(requirement.fields) - set(descriptor.returns))
            if missing_fields:
                raise ValueError(
                    f"analysis {key!r} requires fields {missing_fields} from "
                    f"{requirement.capability_id!r}, which does not return them. Its returns "
                    f"are {sorted(descriptor.returns)}"
                )


def check_window_declarations(
    declarations: Mapping[str, AnalysisDeclaration],
    registry: Mapping[str, RegisteredCapability],
) -> None:
    """Window declarations, as a PURE function so the offline suite can prove it bites.

    Taking the maps as arguments rather than closing over the module's is what makes the
    violation constructible in a test: ``_DECLARATIONS`` is ``Final``, so reassigning it is a
    type error and mutating it would corrupt every test that ran afterwards. Same shape as
    ``check_plan_bindings`` and ``check_envelope``, and for the same reason.

    TWO INVARIANTS, and the second is the one that makes this field the operational half of an
    existing contract field rather than a parameter bolted on:

    1. A named threshold must EXIST on the declaration. Otherwise the KeyError surfaces inside
       resolve_declaration, at the first fetch, for one tenant.

    2. A WINDOW AGAINST A ``LAST_WRITE`` CAPABILITY IS A CONTRADICTION. ``Freshness`` has said
       since slice 1 which capabilities a date parameter is meaningful for: AS_OF_DATE means a
       value stamped with the date it describes, LAST_WRITE means "whatever the row says now,
       asking for yesterday is not answerable". Declaring a window against the latter asks a
       question the capability's own contract says has no answer, and it would silently pass a
       ``date_from``/``date_to`` the resolver does not accept.
    """
    for analysis_id, declaration in declarations.items():
        names = {threshold.name for threshold in declaration.thresholds}
        for requirement in declaration.requires:
            wanted = requirement.window_from_threshold
            if wanted is None:
                continue
            if wanted not in names:
                raise ValueError(
                    f"analysis {analysis_id!r} requires {requirement.capability_id!r} over a "
                    f"{wanted!r} window, but declares no threshold by that name; it has "
                    f"{sorted(names)}"
                )
            entry = registry.get(requirement.capability_id)
            if entry is None:  # pragma: no cover - _check_declarations rejects this first
                continue
            if entry.descriptor.freshness is not Freshness.AS_OF_DATE:
                raise ValueError(
                    f"analysis {analysis_id!r} declares a {wanted!r} window against "
                    f"{requirement.capability_id!r}, whose freshness is "
                    f"{entry.descriptor.freshness.value!r}. A date window is only meaningful for "
                    "AS_OF_DATE: LAST_WRITE says asking for a past date is not answerable, so "
                    "the window would be a question the capability cannot answer"
                )


def _check_windows() -> None:
    """The import-time call. See ``check_window_declarations`` for the invariants."""
    check_window_declarations(_DECLARATIONS, _REGISTRY)


def _check_analyses() -> None:
    """Evaluator invariants, checked at IMPORT.

    - every declaration has an evaluator, and every evaluator a declaration. A declaration with
      no evaluator is an analysis that cannot run — the artifact class this project keeps
      deleting — and an evaluator with no declaration is arithmetic nothing describes.
    - THE EMITS CHECK: the evaluator's row type must match ``emits`` field-for-field. This is the
      fourth mechanical use of the declaration (after grain containment, fields-in-returns, and
      gate binding), and it is what stops ``emits`` being a parallel list that drifts from the
      code. A declaration promising ``days_since_last_sale`` while the evaluator returns
      ``days_since_sale`` would otherwise be caught by nobody until a consumer read the wrong
      attribute.
    """
    missing_evaluator = sorted(set(_DECLARATIONS) - set(_ANALYSES))
    if missing_evaluator:
        raise ValueError(
            f"{missing_evaluator} are declared but have no evaluator; a declaration that cannot "
            "run is a description of nothing"
        )
    orphan_evaluator = sorted(set(_ANALYSES) - set(_DECLARATIONS))
    if orphan_evaluator:
        raise ValueError(f"{orphan_evaluator} have an evaluator but no declaration")

    for analysis_id, declaration in _DECLARATIONS.items():
        row_type = _EVALUATOR_ROWS.get(analysis_id)
        if row_type is None:
            raise ValueError(f"{analysis_id!r} has an evaluator but no declared row type")
        produced = set(getattr(row_type, "__dataclass_fields__", {}))
        promised = set(declaration.emits)
        if produced != promised:
            raise ValueError(
                f"analysis {analysis_id!r} emits {sorted(promised)} but its evaluator returns "
                f"{row_type.__name__} with fields {sorted(produced)}. The declaration's promise "
                "about what it produces must BE what the code produces"
            )


def _check_actions() -> None:
    """Action-proposer invariants, checked at IMPORT.

    - every proposer has a declaration. A proposer with none is arithmetic nothing describes.
    - EVERY DECLARATION WITH A PROPOSER HAS A HOLDOUT. This is the mechanical form of "assignment
      exists from the first action ever recorded": a proposer with no holdout would have to
      fabricate an arm or omit one, and an action recorded without an arm is permanently
      unanalysable because a control group cannot be constructed retrospectively.
    - THE HOLDOUT UNIT IS CONTAINED IN THE ANALYSIS GRAIN. Assigning over a column the analysis
      does not identify rows by is not assignment — the proposer would have no value to hash, and
      the failure would be a KeyError deep inside a loop rather than a statement about the design.
    """
    orphan = sorted(set(_ACTIONS) - set(_DECLARATIONS))
    if orphan:
        raise ValueError(f"{orphan} have an action proposer but no declaration")

    for analysis_id in sorted(_ACTIONS):
        declaration = _DECLARATIONS[analysis_id]
        holdout = declaration.holdout
        if holdout is None:
            raise ValueError(
                f"analysis {analysis_id!r} proposes actions but declares no holdout. Assignment "
                "must exist from the first action ever recorded; a counterfactual cannot be "
                "constructed retrospectively"
            )
        outside = sorted(set(holdout.unit) - set(declaration.grain))
        if outside:
            raise ValueError(
                f"analysis {analysis_id!r} assigns holdout over {outside}, which is not in its "
                f"grain {sorted(declaration.grain)}; there would be no value to assign on"
            )


def check_plan_bindings(
    plans: Mapping[str, Plan],
    actions: Mapping[str, Proposer],
    declarations: Mapping[str, AnalysisDeclaration],
) -> None:
    """Plan invariants, as a PURE function so the offline suite can prove it bites.

    Taking the three maps as arguments rather than closing over the module's is what makes the
    violation constructible in a test: ``_PLANS`` is ``Final``, so a test that reassigned it
    would be a type error, and one that mutated it would leave the registry wrong for every test
    that ran afterwards. The same shape as ``check_envelope`` in the provision loader, and for
    the same reason — the live suite only runs inside a staging window.

    EVERY ANALYSIS THAT PROPOSES ACTIONS MUST HAVE A PLAN, and that is the direction that bites.
    ``actions`` says an analysis can produce actions; a plan is the only thing that can make it
    do so. A proposer with no plan is an analysis the orchestrator would enumerate, resolve, and
    then silently do nothing for — provisioned, apparently healthy, producing a run row with zero
    actions forever. That is indistinguishable from "this tenant genuinely has no dead stock",
    which is precisely the confusion ``synapse.run`` exists to prevent.

    The converse is also refused: a plan for an analysis nothing declares is arithmetic bound to
    a name no declaration claims.
    """
    missing = sorted(set(actions) - set(plans))
    if missing:
        raise ValueError(
            f"{missing} propose actions but have no plan. The orchestrator would resolve them "
            "and produce nothing, which reads exactly like a tenant with no findings"
        )
    orphan = sorted(set(plans) - set(declarations))
    if orphan:
        raise ValueError(f"{orphan} have a plan but no declaration")


def _check_plans() -> None:
    """The import-time call. See ``check_plan_bindings`` for the invariants."""
    check_plan_bindings(_PLANS, _ACTIONS, _DECLARATIONS)


_check_registry()
_check_declarations()
_check_analyses()
_check_windows()
_check_actions()
_check_plans()


def declared_analysis_ids() -> tuple[str, ...]:
    """Every analysis id declared today. Sorted, for a console listing."""
    return tuple(sorted(_DECLARATIONS))


def registered_ids() -> tuple[str, ...]:
    """Every capability id that can resolve today. Sorted, for a console listing."""
    return tuple(sorted(_REGISTRY))


def declined_ids() -> tuple[str, ...]:
    """Every id with a recorded reason for never resolving. Sorted."""
    return tuple(sorted(_DECLINED))


def max_rungs() -> Mapping[str, Rung]:
    """Every declared analysis's autonomy CEILING, for the provision loader to check against.

    The envelope half of the envelope/selection split, handed to a layer that cannot import it:
    ``synapse.persistence`` sits BELOW this module in the import-linter layer order, so the
    loader takes the ceilings as an argument rather than reaching up for them. Injection, the
    same as a resolver taking its engine.

    Every declaration appears, including those with no proposer. A provision naming an analysis
    that produces no actions is legal — it resolves, records a run and appends nothing — and
    should not be refused as unknown.
    """
    return MappingProxyType(
        {analysis_id: declaration.max_rung for analysis_id, declaration in _DECLARATIONS.items()}
    )


def plan_for(analysis_id: str) -> Plan | None:
    """The adapter that runs ``analysis_id``, or ``None`` if it proposes no actions.

    ``None`` is a legitimate answer rather than an error: a declaration may exist to be resolved
    and evaluated without anything acting on its findings. ``_check_plans`` guarantees the case
    that WOULD be a bug — a proposer with no plan — cannot reach here.
    """
    return _PLANS.get(analysis_id)


def declaration_for(analysis_id: str) -> AnalysisDeclaration | None:
    """One declaration by id, or ``None``. For a caller that has an id from a provision row."""
    return _DECLARATIONS.get(analysis_id)


async def resolve(
    engine: AsyncEngine,
    capability_id: str,
    scope: CapabilityScope,
    *,
    gates: tuple[Gate, ...],
    store_id: UUID | None = None,
    sku_id: str | None = None,
    **narrowing: object,
) -> Resolution[object]:
    """Answer whether ``capability_id`` can be satisfied for ``scope`` right now.

    Returns one of three outcomes and never ``None``; see ``synapse.core.resolution`` for
    why that is the whole design rather than a style choice.

    EVERY declared precondition is evaluated, not just up to the first failure: reporting
    one unmet gate would hide the second the day a capability declares two, and the probes
    are cheap counts.

    ``gates`` IS REQUIRED AND HAS NO DEFAULT, and that is the breaking change slice 2 makes to
    a slice-1 signature. It is deliberate. The threshold and the policy both arrive here bound
    together on each gate, supplied by whoever is asking — an analysis declaration, or a console
    that must now say what it means.

    A DEFAULT WOULD MAKE THE GATE DECORATIVE. Defaulting ``gates=()`` would let
    ``resolve(engine, "daily_series", scope)`` skip a declared gate entirely and answer
    Satisfied, which is a free verdict with nobody having said what enough means. Defaulting the
    POLICY would be worse: it would reinstate exactly the unowned default slice 2 deleted. So
    a caller with no gates passes ``gates=()`` explicitly — an empty tuple is a claim, a missing
    argument is a silence, and this codebase already refuses to let those be the same value.

    THE SUPPLIED KINDS MUST EQUAL THE DECLARED KINDS EXACTLY. Not a subset: an unbound declared
    gate never runs. Not a superset: a bound gate the capability does not declare has no probe
    and no checked grain. A mismatch RAISES rather than returning an outcome, because it is a
    caller bug like a bad keyword — not a state of the tenant's data, which is what the three
    outcomes describe.

    ``store_id`` and ``sku_id`` go to BOTH the probes and the resolver — they narrow which
    series are in question, so a gate that ignored them would be answering about a different
    population than the one the caller would receive. They are forwarded only when non-None,
    so a resolver without a given narrowing (``current_state`` has no ``sku_id``) is not
    handed a keyword it cannot accept. Any other ``narrowing`` goes to the resolver only, and
    a resolver that does not accept a given keyword raises ``TypeError`` when ``fetch`` is
    awaited.

    On ``Satisfied``, the returned ``fetch`` is bound but NOT called — the availability
    question must not cost a full read.
    """
    entry = _REGISTRY.get(capability_id)
    if entry is None:
        return Unregistered(
            capability_id=capability_id,
            declined_reason=_DECLINED.get(capability_id),
        )

    bound = {kind: (required, policy) for kind, required, policy in map(_bound, gates)}
    declared = set(entry.descriptor.gates)
    if set(bound) != declared:
        raise ValueError(
            f"{capability_id!r} declares gates {sorted(declared)} but the call bound "
            f"{sorted(bound)}. Every declared gate must be bound (an unbound gate never runs) "
            "and no other may be (it has no probe and no checked grain)"
        )

    unmet: list[PreconditionReport] = []
    # The subjects that cleared EVERY gate. None until a probe reports identities; thereafter
    # the INTERSECTION across gates, because a series must clear all of them to be fetched.
    # With one gate kind in existence this is just that gate's set, but the intersection is the
    # correct semantics and costs nothing to write now rather than discovering it with a second.
    qualifying: set[tuple[str, ...]] | None = None
    for kind, (required, policy) in bound.items():
        observation = await entry.probes[kind].measure(
            engine, scope, store_id=store_id, sku_id=sku_id, required=required
        )
        if observation.qualifying is not None:
            found = set(observation.qualifying)
            qualifying = found if qualifying is None else (qualifying & found)
        report = PreconditionReport(
            name=kind,
            required=required,
            pairs_measured=observation.pairs_measured,
            pairs_qualifying=observation.pairs_qualifying,
            measured_at=observation.measured_at,
        )
        # THE ONE PLACE POLICY MEETS MEASUREMENT, and the only place that knows which policy was
        # asked for. Every gate is evaluated, not just up to the first failure: reporting one
        # unmet gate would hide the second the day a capability declares two.
        if not satisfies(policy, report):
            unmet.append(report)

    if unmet:
        return PreconditionUnmet(descriptor=entry.descriptor, unmet=tuple(unmet))

    resolver = entry.resolver
    forwarded: dict[str, object] = dict(narrowing)
    if store_id is not None:
        forwarded["store_id"] = store_id
    if sku_id is not None:
        forwarded["sku_id"] = sku_id

    # THE NARROWING IS BAKED INTO THE CLOSURE, not handed to the caller as advice.
    #
    # Satisfied also carries `qualifying`, but only so a consumer can INSPECT the population a
    # verdict was made about. The fetch is already narrowed by the time anyone sees it, so a
    # caller that never reads the field still gets rows for exactly the qualifying series. If
    # applying it were the caller's job, forgetting would silently reproduce the bug this
    # discharges — rows for series the gate refused — one layer further from where it is visible.
    ordered = tuple(sorted(qualifying)) if qualifying is not None else None
    if ordered is not None:
        forwarded["only_series"] = ordered

    async def fetch() -> Sequence[object]:
        return await resolver(engine, scope, **forwarded)

    return Satisfied(descriptor=entry.descriptor, fetch=fetch, qualifying=ordered)


async def resolve_declaration(
    engine: AsyncEngine,
    analysis_id: str,
    scope: CapabilityScope,
    *,
    as_of: date | None = None,
    store_id: UUID | None = None,
    sku_id: str | None = None,
) -> DeclarationResolution:
    """Answer whether an ANALYSIS can run for ``scope`` right now, and hand back its inputs.

    The consumer that makes a declaration RUN rather than merely cohere. Until this existed,
    ``_check_declarations()`` verified at import that dead_stock's grain was joinable and its
    fields were real, and nothing had ever fetched a row for it.

    ONE ``resolve()`` PER REQUIREMENT, WITH THE DECLARATION'S OWN GATES. This is where slice 2's
    inversion pays off: the thresholds and policies come from the declaration, so two analyses
    requiring the same capability at different thresholds each get their own answer, and neither
    can be given a verdict nobody asked for.

    EVERY REQUIREMENT IS EVALUATED, never short-circuited on the first block. An operator about
    to provision one missing capability needs to know the other is also missing, or they will fix
    one thing and re-run to discover the next. Costs one extra cheap probe per blocked
    requirement.

    ALL-OR-NOTHING, and see ``synapse.core.declaration_resolution`` for why it is structural: for
    dead_stock, resolving only ``last_sale_at`` would not give half an answer, it would report the
    entire catalogue as dead because there is no universe to date against.

    NARROWING IS store_id / sku_id PLUS A DECLARED DATE WINDOW. The note that stood here said
    the declaration had no field for per-capability call arguments, that inventing one would be
    guessing at a shape no analysis had asked for, and that the first analysis needing one would
    force the field. ``stockout_risk`` is that analysis and the field is
    ``CapabilityRequirement.window_from_threshold``.

    ``as_of`` IS REQUIRED WHEN ANY REQUIREMENT DECLARES A WINDOW, and optional otherwise. A
    window is relative to the moment of asking — ``date_from = as_of - (days - 1)``,
    ``date_to = as_of`` — so it cannot be a literal in a declaration, and the threshold it is
    computed from is one the declaration already carries. Omitting ``as_of`` for an analysis that
    needs one raises here rather than surfacing as a ``TypeError`` on a missing keyword the first
    time somebody awaits a fetch.

    THE FETCHES ARE BOUND, NOT CALLED — same posture as ``Satisfied``, so asking "could this run"
    does not cost two full reads.

    THE CROSS-CAPABILITY SKEW IS ACCEPTED AND NAMED. Each requirement is probed and fetched in its
    own ``rls_session`` transaction, so a two-capability answer joins two snapshots taken at
    different instants. Concretely: a SKU's first sale arriving between the two fetches makes
    ``last_sale_at`` return a position ``current_state`` did not, which looks exactly like a
    violation of the subset claim dead_stock rests on and is pure timing.

    ONE TRANSACTION WOULD NOT CLOSE IT, which is why this does not try. Postgres defaults to READ
    COMMITTED, where each statement takes its own snapshot, so two SELECTs in one transaction
    still see different instants; closing it needs REPEATABLE READ. ``dis_rls.rls_session`` has no
    isolation parameter, and ``SET TRANSACTION ISOLATION LEVEL`` must precede any query in the
    transaction while ``rls_session`` issues its posture guard and both ``set_config`` calls before
    yielding — so it cannot be set from outside ``dis_rls`` at all. And a held transaction is the
    wrong shape for a call whose fetches a caller may hold indefinitely: a pinned connection and a
    long-running transaction while somebody looks at a page. The fix is an isolation parameter on
    ``rls_session`` plus connection-accepting resolvers, which is a DIS-side change and its own
    slice. Recorded rather than quietly carried.

    Raises ``ValueError`` if a requirement's gate binding does not match what the capability
    declares — a caller bug surfaced by ``resolve()``, not a state of the tenant's data.
    """
    declaration = _DECLARATIONS.get(analysis_id)
    if declaration is None:
        return DeclarationUndeclared(analysis_id=analysis_id)

    thresholds = {threshold.name: threshold.days for threshold in declaration.thresholds}
    resolutions: dict[str, Satisfied[object]] = {}
    blocked: dict[str, Resolution[object]] = {}
    for requirement in declaration.requires:
        # THE DECLARED DATE WINDOW, computed here because it is relative to the moment of asking
        # and therefore cannot be a literal in a declaration. The threshold it comes from is one
        # the declaration already carries, so there is no second source for the number.
        window: dict[str, object] = {}
        if requirement.window_from_threshold is not None:
            if as_of is None:
                raise ValueError(
                    f"analysis {analysis_id!r} requires {requirement.capability_id!r} over a "
                    f"{requirement.window_from_threshold!r} window, so resolve_declaration needs "
                    "as_of. A window is relative to the moment of asking"
                )
            days = thresholds[requirement.window_from_threshold]
            window = {"date_from": as_of - timedelta(days=days - 1), "date_to": as_of}

        outcome = await resolve(
            engine,
            requirement.capability_id,
            scope,
            gates=requirement.gates,
            store_id=store_id,
            sku_id=sku_id,
            **window,
        )
        if isinstance(outcome, Satisfied):
            # THE WHOLE Satisfied, not just its fetch: it carries the descriptor and therefore the
            # capability VERSION, which provenance needs and which slice 3 discarded here.
            resolutions[requirement.capability_id] = outcome
        else:
            blocked[requirement.capability_id] = outcome

    if blocked:
        return DeclarationBlocked(declaration=declaration, blocked=blocked)
    return DeclarationSatisfied(declaration=declaration, resolutions=resolutions)


__all__ = [
    "Evaluator",
    "Probe",
    "ProbeBinding",
    "Plan",
    "Proposer",
    "RegisteredCapability",
    "Resolver",
    "check_plan_bindings",
    "check_window_declarations",
    "declaration_for",
    "declared_analysis_ids",
    "declined_ids",
    "max_rungs",
    "plan_for",
    "registered_ids",
    "resolve",
    "resolve_declaration",
]
