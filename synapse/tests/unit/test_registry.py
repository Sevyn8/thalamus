"""The registry and the resolution engine, offline. Stub probes; no engine is ever used.

THE THREE TESTS THAT MATTER MOST are the ones proving the third outcome survives the round
trip: ``resolve()`` on a capability whose precondition is unmet must return
``PreconditionUnmet`` carrying the declared requirement and the measured observation — not
``Unregistered``, not ``None``, and not a raise. Everything else here guards the registry's
own invariants, each of which fails silently if unchecked.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import MappingProxyType
from typing import cast
from uuid import UUID

import pytest
from sqlalchemy.ext.asyncio import AsyncEngine

from synapse import registry as registry_module
from synapse.core.capability import (
    CURRENT_STATE,
    DAILY_SERIES,
    CapabilityDescriptor,
    CapabilityScope,
    Freshness,
    MinHistoryDays,
    Tenancy,
)
from synapse.core.resolution import (
    Observation,
    PreconditionUnmet,
    Satisfied,
    Unregistered,
)
from synapse.registry import (
    _REGISTRY,
    ProbeBinding,
    RegisteredCapability,
    _check_registry,
    _required_days,
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
                        MinHistoryDays.name: ProbeBinding(
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
    assert registered_ids() == ("current_state", "daily_series")


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
        declared = {_required_days(p)[0] for p in entry.descriptor.preconditions}
        assert declared == set(entry.probes)


def test_current_state_registers_no_probes_because_it_declares_no_preconditions() -> None:
    """Verified-empty on both sides, not merely unpopulated."""
    entry = _REGISTRY["current_state"]
    assert entry.descriptor.preconditions == ()
    assert dict(entry.probes) == {}


def test_daily_series_pairs_its_declared_precondition_with_a_probe() -> None:
    entry = _REGISTRY["daily_series"]
    assert entry.descriptor.preconditions == (MinHistoryDays(days=60),)
    assert set(entry.probes) == {"min_history_days"}


def test_the_registry_check_catches_a_key_that_does_not_match(monkeypatch: pytest.MonkeyPatch) -> None:
    """Prove the guard bites."""
    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        MappingProxyType({"typo": _REGISTRY["current_state"]}),
    )
    with pytest.raises(ValueError, match="does not match descriptor id"):
        _check_registry()


def test_the_registry_check_catches_a_declared_precondition_with_no_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE VACUOUS-GATE GUARD. Without it, daily_series would resolve for every tenant while
    still declaring a sixty-day requirement, and the declaration would be decoration."""
    unprobed = RegisteredCapability(
        descriptor=DAILY_SERIES,
        resolver=_REGISTRY["daily_series"].resolver,
        probes=MappingProxyType({}),
    )
    monkeypatch.setattr(registry_module, "_REGISTRY", MappingProxyType({DAILY_SERIES.id: unprobed}))
    with pytest.raises(ValueError, match="gate that always passes"):
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
    outcome = await resolve(NO_ENGINE, "dialy_series", SCOPE)
    assert isinstance(outcome, Unregistered)
    assert outcome.capability_id == "dialy_series"
    assert outcome.declined_reason is None


async def test_a_declined_capability_resolves_to_unregistered_with_a_reason() -> None:
    """The distinction a naive registry cannot make: this is not a typo, and the reason says
    what was actually verified rather than "not available"."""
    outcome = await resolve(NO_ENGINE, "lead_time_distribution", SCOPE)
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
    outcome = await resolve(NO_ENGINE, "daily_series", SCOPE)

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
    outcome = await resolve(NO_ENGINE, "daily_series", SCOPE)
    assert isinstance(outcome, PreconditionUnmet)
    assert outcome.unmet[0].required == DAILY_SERIES.preconditions[0].days
    assert calls[0][1] == (None, None, DAILY_SERIES.preconditions[0].days)


async def test_a_met_precondition_resolves_to_satisfied_without_fetching(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Availability must not cost a read: the probe runs, the resolver does not."""
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=42, calls=calls))

    outcome = await resolve(NO_ENGINE, "daily_series", SCOPE, store_id=STORE)

    assert isinstance(outcome, Satisfied)
    assert [kind for kind, _ in calls] == ["probe"], "the resolver must not have run yet"
    assert calls[0][1] == (STORE, None, 60), "narrowing must reach the probe, not just the resolver"

    assert await outcome.fetch() == ["row"]
    assert [kind for kind, _ in calls] == ["probe", "resolve"]


async def test_one_qualifying_series_is_enough_under_the_placeholder_policy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The placeholder policy, end to end. Replacing it in slice 2 must break this test."""
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=1))
    assert isinstance(await resolve(NO_ENGINE, "daily_series", SCOPE), Satisfied)
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=0))
    assert isinstance(await resolve(NO_ENGINE, "daily_series", SCOPE), PreconditionUnmet)


async def test_narrowing_reaches_the_resolver_and_store_id_reaches_both(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, object]] = []
    monkeypatch.setattr(registry_module, "_REGISTRY", _stub_registry(qualifying=42, calls=calls))

    outcome = await resolve(
        NO_ENGINE, "daily_series", SCOPE, store_id=STORE, sku_id="SKU-000123", limit=10
    )
    assert isinstance(outcome, Satisfied)
    await outcome.fetch()

    narrowing = dict(cast(dict[str, object], calls[1][1]))
    assert narrowing == {"store_id": STORE, "sku_id": "SKU-000123", "limit": 10}
    # ...and the SAME narrowing reached the probe, so the gate measured the population the
    # caller would actually receive rather than the whole tenant.
    assert calls[0][1] == (STORE, "SKU-000123", 60)


async def test_a_capability_with_no_preconditions_needs_no_probe_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """current_state resolves without any measurement, which is what an empty precondition
    tuple MEANS rather than an unpopulated field."""
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
    outcome = await resolve(NO_ENGINE, "current_state", SCOPE)
    assert isinstance(outcome, Satisfied)
    assert calls == []


async def test_every_declared_precondition_is_evaluated_not_just_the_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A capability declaring two gates must report BOTH unmet ones, or the second stays
    invisible until the first is fixed.

    Built with a synthetic two-precondition descriptor, since no real capability declares
    two yet — the shape must work before one does.
    """
    two_gates = CapabilityDescriptor(
        id="two_gates",
        version="0.1.0",
        grain=("tenant_id", "event_date"),
        tenancy=Tenancy.TENANT_SCOPED,
        freshness=Freshness.AS_OF_DATE,
        returns=("tenant_id", "event_date"),
        produces_signals=(),
        preconditions=(MinHistoryDays(days=60), MinHistoryDays(days=90)),
    )

    probe_calls: list[int] = []

    async def probe(
        engine: AsyncEngine,
        scope: CapabilityScope,
        *,
        store_id: UUID | None = None,
        sku_id: str | None = None,
        required: int,
    ) -> Observation:
        probe_calls.append(required)
        return Observation(pairs_measured=66, pairs_qualifying=0, measured_at=MEASURED_AT)

    async def resolver(engine: AsyncEngine, scope: CapabilityScope, **narrowing: object) -> list[object]:
        return []

    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        MappingProxyType(
            {
                "two_gates": RegisteredCapability(
                    descriptor=two_gates,
                    resolver=resolver,
                    probes=MappingProxyType(
                        {
                            MinHistoryDays.name: ProbeBinding(
                                measure=probe, series_grain=("tenant_id",), date_column="event_date"
                            )
                        }
                    ),
                )
            }
        ),
    )
    outcome = await resolve(NO_ENGINE, "two_gates", SCOPE)
    assert isinstance(outcome, PreconditionUnmet)
    assert len(outcome.unmet) == 2, "both gates must be reported"
    assert sorted(r.required for r in outcome.unmet) == [60, 90]
    assert len(probe_calls) == 2


# ---------------------------------------------------------------------------
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
    binding = _REGISTRY["daily_series"].probes["min_history_days"]
    assert binding.series_grain == ("tenant_id", "store_id", "sku_id")
    assert binding.date_column == "event_date"
    assert set(binding.series_grain) | {binding.date_column} == set(DAILY_SERIES.grain)


def test_the_probe_grain_comes_from_the_resolver_not_the_registry() -> None:
    """The binding imports SERIES_GRAIN / DATE_COLUMN from the module whose GROUP BY is built
    from them, so the declaration cannot describe a query it does not implement. Retyping the
    tuple here would be a second source of truth for the same fact."""
    binding = _REGISTRY["daily_series"].probes["min_history_days"]
    assert binding.series_grain is SERIES_GRAIN
    assert binding.date_column is DATE_COLUMN


def _binding(series_grain: tuple[str, ...], date_column: str) -> ProbeBinding:
    return ProbeBinding(
        measure=_REGISTRY["daily_series"].probes["min_history_days"].measure,
        series_grain=series_grain,
        date_column=date_column,
    )


def _registry_with(binding: ProbeBinding) -> MappingProxyType[str, RegisteredCapability]:
    return MappingProxyType(
        {
            DAILY_SERIES.id: RegisteredCapability(
                descriptor=DAILY_SERIES,
                resolver=_REGISTRY["daily_series"].resolver,
                probes=MappingProxyType({MinHistoryDays.name: binding}),
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


def test_a_capability_with_no_preconditions_is_exempt_from_the_grain_rule() -> None:
    """current_state has no probe to check, and that is not a gap. The rule applies to
    measurements; a capability with nothing to measure has nothing to get wrong."""
    assert dict(_REGISTRY["current_state"].probes) == {}
    _check_registry()
