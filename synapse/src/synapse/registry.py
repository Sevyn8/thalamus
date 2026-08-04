"""The capability registry, the analysis declarations, and the resolution engine. ALL DATA.

Three mappings and one function. ``_REGISTRY`` binds a capability id to its descriptor, its
resolver and its gate probes; ``_DECLINED`` records ids that will never have an entry, and why;
``_DECLARATIONS`` holds the analysis declarations. ``resolve()`` reads them and returns one of
the three outcomes in ``synapse.core.resolution``. There is no dispatch on capability id or
analysis id anywhere — adding either is adding a row, and every invariant below is checked at
import rather than trusted.

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
from dataclasses import dataclass
from types import MappingProxyType
from typing import Final, Protocol, assert_never
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from synapse.core.analysis import DEAD_STOCK, AnalysisDeclaration, Gate, MinHistoryDays
from synapse.core.capability import (
    CURRENT_STATE,
    DAILY_SERIES,
    LAST_SALE_AT,
    CapabilityDescriptor,
    CapabilityScope,
    GateKind,
)
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
# here, never editing an engine. Nothing consumes their output yet (no scorer, no action, no
# delivery) — what exists is the declaration and the cross-checks below, which is what makes
# the declaration a contract rather than a comment.
_DECLARATIONS: Final[Mapping[str, AnalysisDeclaration]] = MappingProxyType(
    {
        DEAD_STOCK.id: DEAD_STOCK,
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

    Gate BINDING is checked at resolve() rather than here: a declaration may legitimately be
    written before the capability grows a gate, and the binding that matters is the one on the
    call. See ``resolve``.
    """
    for key, declaration in _DECLARATIONS.items():
        if key != declaration.id:
            raise ValueError(
                f"declaration key {key!r} does not match analysis id {declaration.id!r}"
            )
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


_check_registry()
_check_declarations()


def declared_analysis_ids() -> tuple[str, ...]:
    """Every analysis id declared today. Sorted, for a console listing."""
    return tuple(sorted(_DECLARATIONS))


def registered_ids() -> tuple[str, ...]:
    """Every capability id that can resolve today. Sorted, for a console listing."""
    return tuple(sorted(_REGISTRY))


def declined_ids() -> tuple[str, ...]:
    """Every id with a recorded reason for never resolving. Sorted."""
    return tuple(sorted(_DECLINED))


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
    for kind, (required, policy) in bound.items():
        observation = await entry.probes[kind].measure(
            engine, scope, store_id=store_id, sku_id=sku_id, required=required
        )
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

    async def fetch() -> Sequence[object]:
        return await resolver(engine, scope, **forwarded)

    return Satisfied(descriptor=entry.descriptor, fetch=fetch)


__all__ = [
    "Probe",
    "ProbeBinding",
    "RegisteredCapability",
    "Resolver",
    "declared_analysis_ids",
    "declined_ids",
    "registered_ids",
    "resolve",
]
