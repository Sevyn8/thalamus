"""The registry and the resolution engine, offline. Stub probes; no engine is ever used.

THE THREE TESTS THAT MATTER MOST are the ones proving the third outcome survives the round
trip: ``resolve()`` on a capability whose precondition is unmet must return
``PreconditionUnmet`` carrying the declared requirement and the measured observation — not
``Unregistered``, not ``None``, and not a raise. Everything else here guards the registry's
own invariants, each of which fails silently if unchecked.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from synapse import registry as registry_module
from synapse.core.analysis import (
    DEAD_STOCK,
    AnalysisDeclaration,
    CapabilityRequirement,
    MinHistoryDays,
)
from synapse.core.capability import (
    CURRENT_STATE,
    DAILY_SERIES,
    CapabilityScope,
    GateKind,
)
from synapse.core.resolution import (
    Observation,
    PreconditionUnmet,
    Satisfied,
    SeriesPolicy,
    Unregistered,
)
from synapse.registry import (
    _REGISTRY,
    ProbeBinding,
    RegisteredCapability,
    _check_declarations,
    _check_registry,
    declared_analysis_ids,
    declined_ids,
    registered_ids,
    resolve,
)
from synapse.resolvers.daily_series import DATE_COLUMN, SERIES_GRAIN

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
SCOPE = CapabilityScope(tenant_id=TENANT)
NO_ENGINE = cast(AsyncEngine, None)
MEASURED_AT = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)

# The gate a caller binds. ANY_SERIES because most of these tests assert plumbing rather than
# policy; the policy itself is exercised in test_resolution_outcomes and below.
_GATE = MinHistoryDays(days=60, policy=SeriesPolicy.ANY_SERIES)


def _stub_registry(
    *,
    qualifying: int,
    measured: int = 66,
    calls: list[tuple[str, object]] | None = None,
) -> MappingProxyType[str, RegisteredCapability]:
    """A registry whose daily_series probe reports a fixed population and whose resolver
    records its call instead of touching a database.

    The probe records the (store_id, sku_id, required) it was handed, so the tests can assert
    that narrowing and the declared threshold reach it — the two things the per-tenant defect
    got wrong.
    """
    recorder = calls if calls is not None else []

    async def probe(
        engine: AsyncEngine,
        scope: CapabilityScope,
        *,
        store_id: UUID | None = None,
        sku_id: str | None = None,
        required: int,
    ) -> Observation:
        recorder.append(("probe", (store_id, sku_id, required)))
        return Observation(
            pairs_measured=measured, pairs_qualifying=qualifying, measured_at=MEASURED_AT
        )

    async def resolver(engine: AsyncEngine, scope: CapabilityScope, **narrowing: object) -> list[object]:
        recorder.append(("resolve", narrowing))
        return ["row"]

    return MappingProxyType(
        {
            DAILY_SERIES.id: RegisteredCapability(
                descriptor=DAILY_SERIES,
                resolver=resolver,
                probes=MappingProxyType(
                    {
                        GateKind.MIN_HISTORY_DAYS: ProbeBinding(
                            measure=probe, series_grain=SERIES_GRAIN, date_column=DATE_COLUMN
                        )
                    }
                ),
            )
        }
    )


# ---------------------------------------------------------------------------
# Registry as data
# ---------------------------------------------------------------------------


def test_the_registry_holds_exactly_the_two_built_capabilities() -> None:
    assert registered_ids() == ("current_state", "daily_series", "last_sale_at")


def test_lead_time_distribution_is_declined_not_registered() -> None:
    """The B decision, pinned. Absence plus a recorded reason — no descriptor, because a
    descriptor is a claim about a row shape and no such row has ever been produced."""
    assert declined_ids() == ("lead_time_distribution",)
    assert "lead_time_distribution" not in registered_ids()


def test_every_key_matches_its_descriptor_id() -> None:
    """A mismatch makes a capability report as unregistered while sitting in the registry."""
    for key, entry in _REGISTRY.items():
        assert key == entry.descriptor.id


def test_every_declared_precondition_has_a_probe() -> None:
    """A declared precondition with no probe is a gate that ALWAYS PASSES — the vacuous
    guard this repo has already been bitten by twice.

    Uses the registry's own name-extraction so this cannot drift from the invariant the
    import-time check enforces.
    """
    for entry in _REGISTRY.values():
        assert set(entry.descriptor.gates) == set(entry.probes)


def test_current_state_registers_no_probes_because_it_declares_no_gates() -> None:
    """Verified-empty on both sides, not merely unpopulated."""
    entry = _REGISTRY["current_state"]
    assert entry.descriptor.gates == ()
    assert dict(entry.probes) == {}


def test_daily_series_pairs_its_declared_precondition_with_a_probe() -> None:
    entry = _REGISTRY["daily_series"]
    assert entry.descriptor.gates == (GateKind.MIN_HISTORY_DAYS,)
    assert set(entry.probes) == {GateKind.MIN_HISTORY_DAYS}


def test_the_registry_check_catches_a_key_that_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove the guard bites."""
    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        MappingProxyType({"typo": _REGISTRY["current_state"]}),
    )
    with pytest.raises(ValueError, match="does not match descriptor id"):
        _check_registry()


def test_the_registry_check_catches_a_declared_gate_with_no_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE VACUOUS-GATE GUARD. A capability may declare a gate kind only where a probe exists;
    otherwise the declaration advertises a measurement nothing can take."""
    unprobed = RegisteredCapability(
        descriptor=DAILY_SERIES,
        resolver=_REGISTRY["daily_series"].resolver,
        probes=MappingProxyType({}),
    )
    monkeypatch.setattr(registry_module, "_REGISTRY", MappingProxyType({DAILY_SERIES.id: unprobed}))
    with pytest.raises(ValueError, match="cannot be measured"):
        _check_registry()


def test_the_registry_check_catches_an_id_that_is_both_registered_and_declined(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        registry_module,
        "_DECLINED",
        MappingProxyType({"daily_series": "contradiction"}),
    )
    with pytest.raises(ValueError, match="both registered and declined"):
        _check_registry()


def test_the_registry_is_immutable() -> None:
    """Data, and not data anything can rewrite at runtime."""
    with pytest.raises(TypeError):
        _REGISTRY["invented"] = _REGISTRY["current_state"]  # type: ignore[index]


# ---------------------------------------------------------------------------
# The three outcomes, end to end
# ---------------------------------------------------------------------------


async def test_a_typo_resolves_to_unregistered_with_no_reason() -> None:
    outcome = await resolve(NO_ENGINE, "dialy_series", SCOPE, gates=())
    assert isinstance(outcome, Unregistered)
    assert outcome.capability_id == "dialy_series"
    assert outcome.declined_reason is None


async def test_a_declined_capability_resolves_to_unregistered_with_a_reason() -> None:
    """The distinction a naive registry cannot make: this is not a typo, and the reason says
    what was actually verified rather than "not available"."""
    outcome = await resolve(NO_ENGINE, "lead_time_distribution", SCOPE, gates=())
    assert isinstance(outcome, Unregistered)
    assert outcome.declined_reason is not None
    assert "lead_time_days" in outcome.declined_reason
    assert "RECEIPT" in outcome.declined_reason


async def test_an_unmet_precondition_resolves_to_precondition_unmet(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE LOAD-BEARING TEST OF THIS SLICE.

    Twelve days of history against a sixty-day requirement is NOT "no such capability". It
    is a registered capability, blocked, with both numbers attached — which is the only way
    an operator can tell "wait 48 days" from "never".
    """
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=0, measured=66))
    outcome = await resolve(NO_ENGINE, "daily_series", SCOPE, gates=(_GATE,))

    assert isinstance(outcome, PreconditionUnmet)
    assert not isinstance(outcome, Unregistered)
    assert outcome.descriptor.id == "daily_series"
    (report,) = outcome.unmet
    assert report.name == "min_history_days"
    assert (report.required, report.pairs_measured, report.pairs_qualifying) == (60, 66, 0)
    assert report.measured_at == MEASURED_AT


async def test_the_required_value_comes_from_the_descriptor_not_the_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A probe is HANDED the threshold and reports only counts, so there is one source for
    the number. Pinned twice: the report's `required` comes from the descriptor, and the probe
    records the value it was handed, which must be the same one."""
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        registry_module, "_REGISTRY", _stub_registry(qualifying=0, measured=5, calls=calls)
    )
    outcome = await resolve(NO_ENGINE, "daily_series", SCOPE, gates=(_GATE,))
    assert isinstance(outcome, PreconditionUnmet)
    assert outcome.unmet[0].required == _GATE.days
    assert calls[0][1] == (None, None, _GATE.days)


async def test_a_met_precondition_resolves_to_satisfied_without_fetching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Availability must not cost a read: the probe runs, the resolver does not."""
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=42, calls=calls))

    outcome = await resolve(NO_ENGINE, "daily_series", SCOPE, gates=(_GATE,), store_id=STORE)

    assert isinstance(outcome, Satisfied)
    assert [kind for kind, _ in calls] == ["probe"], "the resolver must not have run yet"
    assert calls[0][1] == (STORE, None, 60), "narrowing must reach the probe, not just the resolver"

    assert await outcome.fetch() == ["row"]
    assert [kind for kind, _ in calls] == ["probe", "resolve"]


async def test_one_qualifying_series_is_enough_under_the_placeholder_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ANY_SERIES end to end: one qualifying series of 66 resolves.

    This was "the placeholder policy, end to end" and the placeholder is gone. The behaviour
    survived the deletion because ANY_SERIES *is* what the placeholder computed — it is now a
    choice a caller states rather than a default nobody owned.
    """
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=1))
    assert isinstance(await resolve(NO_ENGINE, "daily_series", SCOPE, gates=(_GATE,)), Satisfied)
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=0))
    assert isinstance(
        await resolve(NO_ENGINE, "daily_series", SCOPE, gates=(_GATE,)), PreconditionUnmet
    )


async def test_narrowing_reaches_the_resolver_and_store_id_reaches_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=42, calls=calls))

    outcome = await resolve(
        NO_ENGINE,
        "daily_series",
        SCOPE,
        gates=(_GATE,),
        store_id=STORE,
        sku_id="SKU-000123",
        limit=10,
    )
    assert isinstance(outcome, Satisfied)
    await outcome.fetch()

    narrowing = dict(cast(dict[str, object], calls[1][1]))
    assert narrowing == {"store_id": STORE, "sku_id": "SKU-000123", "limit": 10}
    # ...and the SAME narrowing reached the probe, so the gate measured the population the
    # caller would actually receive rather than the whole tenant.
    assert calls[0][1] == (STORE, "SKU-000123", 60)


async def test_a_capability_with_no_gates_needs_no_probe_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """current_state resolves without any measurement, which is what an empty gates tuple
    MEANS rather than an unpopulated field."""
    calls: list[tuple[str, object]] = []

    async def resolver(engine: AsyncEngine, scope: CapabilityScope, **narrowing: object) -> list[object]:
        calls.append(("resolve", narrowing))
        return []

    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        MappingProxyType(
            {
                CURRENT_STATE.id: RegisteredCapability(
                    descriptor=CURRENT_STATE, resolver=resolver, probes=MappingProxyType({})
                )
            }
        ),
    )
    outcome = await resolve(NO_ENGINE, "current_state", SCOPE, gates=())
    assert isinstance(outcome, Satisfied)
    assert calls == []


def test_two_gates_of_the_same_kind_cannot_be_expressed() -> None:
    """A PROPERTY SLICE 2 REMOVED, recorded rather than quietly dropped.

    Slice 1 had `test_every_declared_precondition_is_evaluated_not_just_the_first`, which built
    a synthetic descriptor declaring `(MinHistoryDays(60), MinHistoryDays(90))` and asserted both
    were reported. That test cannot be written now, and the reason is that the inversion made it
    MEANINGLESS rather than merely awkward: gates are declared as KINDS, a caller binds at most
    one threshold per kind, and two history requirements on one capability is not a thing — you
    would take the max. `CapabilityRequirement` refuses it outright.

    So the "every gate is evaluated, not just the first" property is currently UNEXERCISABLE:
    with one GateKind, "every" is one. It becomes testable the day a second kind exists, and
    `_bound`'s and `satisfies`'s `assert_never` are what force that day to be a visible edit.
    Stating this is better than leaving a deleted test to be noticed as a coverage gap.
    """
    with pytest.raises(ValueError, match="binds a gate kind twice"):
        CapabilityRequirement(
            capability_id="daily_series",
            fields=("tenant_id",),
            gates=(
                MinHistoryDays(days=60, policy=SeriesPolicy.ANY_SERIES),
                MinHistoryDays(days=90, policy=SeriesPolicy.ANY_SERIES),
            ),
        )


async def test_resolve_refuses_a_call_that_leaves_a_declared_gate_unbound() -> None:
    """An unbound declared gate never runs, which makes the declaration decorative.

    This is the failure a default would have caused: `gates=()` against a capability that
    declares one would answer Satisfied without measuring anything.
    """
    with pytest.raises(ValueError, match="Every declared gate must be bound"):
        await resolve(NO_ENGINE, "daily_series", SCOPE, gates=())


async def test_resolve_refuses_a_gate_the_capability_does_not_declare() -> None:
    """The other direction: a bound gate with no probe and no checked grain."""
    with pytest.raises(ValueError, match="no other may be"):
        await resolve(NO_ENGINE, "current_state", SCOPE, gates=(_GATE,))


async def test_the_policy_a_caller_supplies_is_the_one_applied(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE POINT OF SLICE 2, in one assertion: the SAME measurement, two verdicts.

    3 of 66 series qualifying is genuinely satisfied for a caller that needs any series and
    genuinely unmet for one that needs all of them. Slice 1 could not express the difference —
    its module-level placeholder made everyone's answer the ANY answer.
    """
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=3, measured=66))

    any_gate = MinHistoryDays(days=60, policy=SeriesPolicy.ANY_SERIES)
    all_gate = MinHistoryDays(days=60, policy=SeriesPolicy.ALL_SERIES)

    assert isinstance(await resolve(NO_ENGINE, "daily_series", SCOPE, gates=(any_gate,)), Satisfied)
    unmet = await resolve(NO_ENGINE, "daily_series", SCOPE, gates=(all_gate,))
    assert isinstance(unmet, PreconditionUnmet)
    assert (unmet.unmet[0].pairs_qualifying, unmet.unmet[0].pairs_measured) == (3, 66)


async def test_the_threshold_a_caller_supplies_is_the_one_probed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """min_days is a CALLER-SUPPLIED ARGUMENT now. Dead stock's 90 and a forecast's 60 reach
    the same capability's probe as different numbers, which slice 1's descriptor constant made
    impossible."""
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(
        registry_module, "_REGISTRY", _stub_registry(qualifying=66, calls=calls)
    )
    for days in (60, 90):
        await resolve(
            NO_ENGINE,
            "daily_series",
            SCOPE,
            gates=(MinHistoryDays(days=days, policy=SeriesPolicy.ANY_SERIES),),
        )
    assert [call[1][2] for call in calls if call[0] == "probe"] == [60, 90]  # type: ignore[index]


# THE GRAIN RULE — a precondition is measured at the declared grain minus the date
#
# The only one of the per-tenant defect's findings that GENERALISES, so it is enforced at
# registry import rather than described in one resolver's comments. The defect: daily_series
# declares grain (tenant_id, store_id, sku_id, event_date) and its first probe measured at
# (tenant_id) — one number for the whole tenant, clearing a 60-day threshold on data where
# every individual series had ~9 observations.
# ---------------------------------------------------------------------------


def test_the_real_registry_satisfies_the_grain_rule() -> None:
    """The live binding, checked. Also non-vacuity: it asserts a probe EXISTS to check."""
    binding = _REGISTRY["daily_series"].probes[GateKind.MIN_HISTORY_DAYS]
    assert binding.series_grain == ("tenant_id", "store_id", "sku_id")
    assert binding.date_column == "event_date"
    assert set(binding.series_grain) | {binding.date_column} == set(DAILY_SERIES.grain)


def test_the_probe_grain_comes_from_the_resolver_not_the_registry() -> None:
    """The binding imports SERIES_GRAIN / DATE_COLUMN from the module whose GROUP BY is built
    from them, so the declaration cannot describe a query it does not implement. Retyping the
    tuple here would be a second source of truth for the same fact."""
    binding = _REGISTRY["daily_series"].probes[GateKind.MIN_HISTORY_DAYS]
    assert binding.series_grain is SERIES_GRAIN
    assert binding.date_column is DATE_COLUMN


def _binding(series_grain: tuple[str, ...], date_column: str) -> ProbeBinding:
    return ProbeBinding(
        measure=_REGISTRY["daily_series"].probes[GateKind.MIN_HISTORY_DAYS].measure,
        series_grain=series_grain,
        date_column=date_column,
    )


def _registry_with(binding: ProbeBinding) -> MappingProxyType[str, RegisteredCapability]:
    return MappingProxyType(
        {
            DAILY_SERIES.id: RegisteredCapability(
                descriptor=DAILY_SERIES,
                resolver=_REGISTRY["daily_series"].resolver,
                probes=MappingProxyType({GateKind.MIN_HISTORY_DAYS: binding}),
            )
        }
    )


def test_the_grain_rule_catches_a_coarser_measurement(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE EXACT DEFECT, reproduced. Measuring per tenant against a per-series grain.

    This is the assertion that would have failed at write time. It is the reason the rule is
    registry-level: no amount of care inside daily_series.py would have caught a probe that
    was internally consistent and answering a different question.
    """
    monkeypatch.setattr(registry_module, "_REGISTRY", _registry_with(_binding(("tenant_id",), "event_date")))
    with pytest.raises(ValueError, match="measuring coarser answers a different question"):
        _check_registry()


def test_the_grain_rule_catches_a_measurement_missing_only_sku(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Per (tenant, store) is closer and still wrong: a store's calendar is not a SKU's."""
    monkeypatch.setattr(
        registry_module, "_REGISTRY", _registry_with(_binding(("tenant_id", "store_id"), "event_date"))
    )
    with pytest.raises(ValueError, match="declared grain"):
        _check_registry()


def test_the_grain_rule_catches_a_finer_measurement(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wrong in the other direction: gating on a grain the capability never returns."""
    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        _registry_with(_binding(("tenant_id", "store_id", "sku_id", "sku_variant"), "event_date")),
    )
    with pytest.raises(ValueError, match="declared grain"):
        _check_registry()


def test_the_grain_rule_catches_a_date_column_not_in_the_grain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise the exclusion excludes nothing and the equality could be satisfied by an
    invented column name — the way a check passes while protecting nothing."""
    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        _registry_with(_binding(("tenant_id", "store_id", "sku_id", "event_date"), "invented_at")),
    )
    with pytest.raises(ValueError, match="excludes date column"):
        _check_registry()


def test_the_grain_rule_catches_grouping_by_the_date_column(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every group would be one date and every coverage 1 — a gate that always FAILS.

    Wrong in the safe direction is still wrong: it would read as "this tenant has no history"
    forever, and nobody debugs a gate that is refusing conservatively.
    """
    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        _registry_with(_binding(("tenant_id", "store_id", "sku_id", "event_date"), "event_date")),
    )
    with pytest.raises(ValueError, match="groups BY its date column"):
        _check_registry()


def test_a_capability_with_no_gates_is_exempt_from_the_grain_rule() -> None:
    """current_state has no probe to check, and that is not a gap. The rule applies to
    measurements; a capability with nothing to measure has nothing to get wrong."""
    assert dict(_REGISTRY["current_state"].probes) == {}
    _check_registry()


# ---------------------------------------------------------------------------
# THE DECLARATION CHECKS — composition, enforced at import
# ---------------------------------------------------------------------------


def test_the_declarations_are_data_and_immutable() -> None:
    """Adding an analysis is adding a row, never editing an engine — the registry's own rule."""
    assert declared_analysis_ids() == ("dead_stock",)
    with pytest.raises(TypeError):
        registry_module._DECLARATIONS["invented"] = DEAD_STOCK  # type: ignore[index]


def test_the_real_declaration_satisfies_every_cross_check() -> None:
    """Non-vacuity: the checks below are only worth anything if something passes them."""
    _check_declarations()


def _declaring(declaration: AnalysisDeclaration) -> MappingProxyType[str, AnalysisDeclaration]:
    return MappingProxyType({declaration.id: declaration})


def _dead_stock_with(**changes: object) -> AnalysisDeclaration:
    return replace(DEAD_STOCK, **changes)  # type: ignore[arg-type]


def test_the_declaration_check_catches_a_key_that_does_not_match(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        registry_module, "_DECLARATIONS", MappingProxyType({"typo": DEAD_STOCK})
    )
    with pytest.raises(ValueError, match="does not match analysis id"):
        _check_declarations()


def test_the_declaration_check_catches_an_unregistered_capability(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A requirement on a capability that does not exist is a declaration that can never
    resolve — the artifact class this project keeps deleting."""
    broken = _dead_stock_with(
        requires=(
            CapabilityRequirement(capability_id="basket_set", fields=("tenant_id",), gates=()),
        )
    )
    monkeypatch.setattr(registry_module, "_DECLARATIONS", _declaring(broken))
    with pytest.raises(ValueError, match="which is not registered"):
        _check_declarations()


def test_a_requirement_on_a_declined_capability_reports_its_recorded_reason(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE MOST USEFUL ERROR MESSAGE THIS CHECK CAN PRODUCE. Someone who has just written a
    requirement for lead_time_distribution gets told WHY it cannot exist — the verified reason
    from _DECLINED — instead of 'not registered', which reads as 'not built yet'."""
    broken = _dead_stock_with(
        requires=(
            CapabilityRequirement(
                capability_id="lead_time_distribution", fields=("tenant_id",), gates=()
            ),
        )
    )
    monkeypatch.setattr(registry_module, "_DECLARATIONS", _declaring(broken))
    with pytest.raises(ValueError, match="It is DECLINED: No observed lead times"):
        _check_declarations()


def test_the_grain_rule_catches_a_capability_too_coarse_to_join(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE COMPOSITION RULE, and the first mechanical use of the capability contract's `grain`.

    An analysis emitting one row per (tenant, store, sku) cannot join a capability that
    identifies rows only per tenant: the join would invent rows, and no care in the analysis
    body fixes a join that was never valid. Simulated by widening the analysis's grain past what
    its capabilities offer, which is the same inequality from the other side.
    """
    broken = _dead_stock_with(grain=("tenant_id", "store_id", "sku_id", "sku_variant"))
    monkeypatch.setattr(registry_module, "_DECLARATIONS", _declaring(broken))
    with pytest.raises(ValueError, match="does not contain"):
        _check_declarations()


def test_the_field_check_catches_reading_a_field_a_capability_does_not_return(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The check that would catch reaching for a plausible-but-absent field — the most likely
    way an analysis goes quietly wrong."""
    broken = _dead_stock_with(
        requires=(
            CapabilityRequirement(
                capability_id="last_sale_at",
                fields=("tenant_id", "days_since_last_sale"),
                gates=(),
            ),
        )
    )
    monkeypatch.setattr(registry_module, "_DECLARATIONS", _declaring(broken))
    with pytest.raises(ValueError, match="which does not return them"):
        _check_declarations()
