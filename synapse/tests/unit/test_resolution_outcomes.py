"""The three resolution outcomes, offline. No DB, no engine, no registry.

THE LOAD-BEARING TESTS ARE THE ONES ABOUT THE THIRD OUTCOME. "Registered, and this tenant
is 48 days short" is the state a registry returning ``Resolver | None`` cannot express, so
these pin (a) that it is a distinct type, (b) that it carries BOTH the requirement and the
measurement, and (c) that it cannot be constructed claiming something it does not mean.

``test_a_caller_must_handle_all_three`` is the exhaustiveness mechanism at runtime; mypy
--strict is the same mechanism at type-check time, via ``assert_never``.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from typing import assert_never

import pytest

from synapse.core.capability import CURRENT_STATE, DAILY_SERIES, MinHistoryDays
from synapse.core.resolution import (
    Observation,
    PreconditionReport,
    PreconditionUnmet,
    Resolution,
    ResolutionStatus,
    Satisfied,
    Unregistered,
    satisfies_placeholder_policy,
)

MEASURED_AT = datetime(2026, 8, 3, 9, 0, tzinfo=UTC)


def _report(
    *, qualifying: int, measured: int = 66, required: int = 60
) -> PreconditionReport:
    return PreconditionReport(
        name=MinHistoryDays.name,
        required=required,
        pairs_measured=measured,
        pairs_qualifying=qualifying,
        measured_at=MEASURED_AT,
    )


def _render(resolution: Resolution[object]) -> str:
    """What an operator console would render. Exhaustive by construction.

    ``assert_never`` in the fallback is what makes mypy --strict fail a caller that adds a
    fourth outcome and forgets a branch here. That is the enforcement; this function exists
    to prove the three are actually distinguishable in a real branch.
    """
    match resolution:
        case Satisfied():
            return f"available: {resolution.descriptor.id}"
        case PreconditionUnmet():
            gate = resolution.unmet[0]
            return (
                f"blocked: {gate.name} {gate.pairs_qualifying}/{gate.pairs_measured} series "
                f"have {gate.required}+ days"
            )
        case Unregistered():
            if resolution.declined_reason is None:
                return f"unknown: {resolution.capability_id}"
            return f"declined: {resolution.capability_id}"
        case _:  # pragma: no cover - unreachable while Resolution has three members
            assert_never(resolution)


async def _no_rows() -> list[object]:
    return []


def test_a_caller_must_handle_all_three() -> None:
    """Each outcome renders differently — the point of them being three types."""
    assert _render(Satisfied(descriptor=CURRENT_STATE, fetch=_no_rows)) == "available: current_state"
    assert (
        _render(PreconditionUnmet(descriptor=DAILY_SERIES, unmet=(_report(qualifying=0),)))
        == "blocked: min_history_days 0/66 series have 60+ days"
    )
    assert _render(Unregistered(capability_id="dialy_series")) == "unknown: dialy_series"
    assert (
        _render(Unregistered(capability_id="lead_time_distribution", declined_reason="no inputs"))
        == "declined: lead_time_distribution"
    )


def test_the_three_statuses_are_distinct() -> None:
    """The tag is for rendering and logs; a shared value would defeat both."""
    statuses = {Satisfied.status, Unregistered.status, PreconditionUnmet.status}
    assert statuses == {
        ResolutionStatus.SATISFIED,
        ResolutionStatus.UNREGISTERED,
        ResolutionStatus.PRECONDITION_UNMET,
    }
    assert len(statuses) == 3


def test_status_cannot_be_set_per_instance() -> None:
    """A ClassVar, so no variant can be built claiming to be one of the others."""
    with pytest.raises(TypeError):
        Unregistered(capability_id="x", status=ResolutionStatus.SATISFIED)  # type: ignore[call-arg]


def test_an_unregistered_id_carries_no_reason_by_default() -> None:
    """A typo and a verified impossibility must not render the same.

    THE DISTINCTION THAT WOULD OTHERWISE BE LOST. Both are "no entry", and without the
    optional reason an operator asking why they cannot have lead times gets exactly the
    answer they would get for a misspelling.
    """
    assert Unregistered(capability_id="dialy_series").declined_reason is None


def test_a_report_carries_the_requirement_and_the_population() -> None:
    """"Needs 60 days" alone cannot distinguish "wait 48 days" from "never", and a single
    reduced number cannot distinguish "no data" from "one new SKU"."""
    report = _report(qualifying=0, measured=66)
    assert (report.required, report.pairs_measured, report.pairs_qualifying) == (60, 66, 0)
    assert report.measured_at == MEASURED_AT


def test_a_report_carries_no_verdict() -> None:
    """FACTS ONLY. A `met` property on the report would put policy where it looks like a
    fact, and the policy is a slice-1 placeholder that must stay visible as one."""
    fields = set(PreconditionReport.__dataclass_fields__)
    assert fields == {"name", "required", "pairs_measured", "pairs_qualifying", "measured_at"}
    assert not hasattr(_report(qualifying=0), "met")


def test_the_placeholder_policy_is_any_series_qualifying() -> None:
    """Pinned so that replacing it in slice 2 is a visible, deliberate edit.

    NOT MIN, deliberately. MIN reads as a considered conservative choice while being
    unusable: any growing catalogue adds a SKU with 7 days and blocks the whole store
    permanently, so a 5,000-SKU tenant with 4,950 good series would never resolve.
    """
    assert not satisfies_placeholder_policy(_report(qualifying=0, measured=66))
    assert satisfies_placeholder_policy(_report(qualifying=1, measured=66))
    assert satisfies_placeholder_policy(_report(qualifying=66, measured=66))


def test_the_placeholder_policy_refuses_an_empty_population() -> None:
    """A tenant with no series at all is not satisfied. 0 of 0 must not read as "all of
    them qualify", which is what an all-series policy would say here."""
    assert not satisfies_placeholder_policy(_report(qualifying=0, measured=0))


def test_precondition_unmet_refuses_an_empty_report_tuple() -> None:
    """Nothing unmet means Satisfied. Allowing this would let a console render "blocked"
    with no gate to name, which is worse than either honest answer."""
    with pytest.raises(ValueError, match="Satisfied in disguise"):
        PreconditionUnmet(descriptor=DAILY_SERIES, unmet=())


def test_precondition_unmet_refuses_a_satisfied_report() -> None:
    """LOAD-BEARING. The engine filters to unmet reports; if that filter were ever inverted
    or dropped, this type refuses to be constructed rather than reporting a satisfied
    capability as blocked. Checked against the SAME policy the engine used, so the two
    cannot drift."""
    with pytest.raises(ValueError, match="SATISFIED report"):
        PreconditionUnmet(descriptor=DAILY_SERIES, unmet=(_report(qualifying=3),))


def test_precondition_unmet_carries_the_descriptor() -> None:
    """A console renders what the capability WOULD give next to why it cannot yet."""
    unmet = PreconditionUnmet(descriptor=DAILY_SERIES, unmet=(_report(qualifying=0),))
    assert unmet.descriptor.grain == ("tenant_id", "store_id", "sku_id", "event_date")
    assert "net_quantity" in unmet.descriptor.returns


def test_an_observation_carries_no_requirement_and_no_reduced_scalar() -> None:
    """Two things at once, and both were decisions.

    NO THRESHOLD: if Observation had `required`, a probe could report 1 while the descriptor
    declared 60 and nothing would notice. The engine hands the number in instead.

    NO REDUCED SCALAR: a per-series capability has one coverage per series, and reducing
    them is policy. An `observed: int` here would have forced that policy into the probe,
    which is where it is least visible and hardest to replace.
    """
    assert set(Observation.__dataclass_fields__) == {
        "pairs_measured",
        "pairs_qualifying",
        "measured_at",
    }


def test_the_outcomes_are_frozen() -> None:
    outcome = Unregistered(capability_id="x")
    with pytest.raises(FrozenInstanceError):
        outcome.capability_id = "y"  # type: ignore[misc]


async def test_satisfied_holds_a_bound_fetch_that_is_not_yet_called() -> None:
    """Availability must not cost a read. The fetch is bound and waiting."""
    calls: list[str] = []

    async def fetch() -> list[object]:
        calls.append("called")
        return []

    satisfied = Satisfied(descriptor=DAILY_SERIES, fetch=fetch)
    assert calls == [], "constructing Satisfied must not perform the read"
    assert await satisfied.fetch() == []
    assert calls == ["called"]
