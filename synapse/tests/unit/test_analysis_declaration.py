"""The analysis declaration — the DEMAND side, offline. No DB, no engine.

THE LOAD-BEARING TESTS ARE THE ONES ABOUT COMPOSITION AND ABOUT WHAT A CONSTANT MUST ADMIT.
Everything else guards shapes; those two guard claims:

- the composition rule (an analysis's grain contained in every required capability's grain) is
  the first mechanical use of the capability contract's `grain`, and the thing that makes a
  two-capability join checkable rather than hoped for.
- `Threshold` refuses to be constructed as an unexplained constant, which turns the standing
  "fitted where possible, honest where not" instruction from a comment into a mechanism.
"""

from __future__ import annotations

import json
import pathlib
from dataclasses import FrozenInstanceError, replace

import pytest

from synapse.core.analysis import (
    DEAD_STOCK,
    AnalysisDeclaration,
    CapabilityRequirement,
    MinHistoryDays,
    Threshold,
)
from synapse.core.capability import CURRENT_STATE, LAST_SALE_AT, GateKind
from synapse.core.resolution import SeriesPolicy

FIXTURE = (
    pathlib.Path(__file__).resolve().parents[3]
    / "contracts"
    / "synapse"
    / "fixtures"
    / "analysis"
    / "dead_stock.json"
)


# ---------------------------------------------------------------------------
# min_days is a caller-supplied argument now
# ---------------------------------------------------------------------------


def test_a_gate_carries_both_the_threshold_and_the_policy() -> None:
    """THE SLICE-2 SHAPE. Slice 1 had the number on the descriptor and the policy nowhere.

    Both now arrive bound together from the caller, so a capability cannot dictate either and a
    caller cannot supply one without the other.
    """
    gate = MinHistoryDays(days=90, policy=SeriesPolicy.ALL_SERIES)
    assert (gate.days, gate.policy) == (90, SeriesPolicy.ALL_SERIES)
    assert gate.kind is GateKind.MIN_HISTORY_DAYS


def test_a_gate_cannot_be_built_without_a_policy() -> None:
    """A threshold with no policy is slice 1's unowned default coming back."""
    with pytest.raises(TypeError):
        MinHistoryDays(days=90)  # type: ignore[call-arg]


def test_the_same_capability_takes_different_thresholds_from_different_callers() -> None:
    """The whole reason the threshold moved: dead stock's 90 and a forecast's 60 are both
    legitimate requirements ON THE SAME ROWS, and slice 1 could hold only one."""
    dead_stock_gate = MinHistoryDays(days=90, policy=SeriesPolicy.ANY_SERIES)
    forecast_gate = MinHistoryDays(days=60, policy=SeriesPolicy.ALL_SERIES)
    assert dead_stock_gate.days != forecast_gate.days
    assert dead_stock_gate.kind is forecast_gate.kind


def test_a_gate_of_zero_days_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1 day"):
        MinHistoryDays(days=0, policy=SeriesPolicy.ANY_SERIES)


# ---------------------------------------------------------------------------
# Thresholds: the honesty rule as a constructor, not a comment
# ---------------------------------------------------------------------------


def test_an_unfitted_threshold_must_name_what_it_stands_in_for() -> None:
    """THE MECHANISM. The standing rule is that thresholds are fitted from the tenant's own
    data where possible and, where not, the constant names what it substitutes for. That worked
    in slice 1 because a comment was there to be read — but a comment cannot be enforced and
    the next constant might not carry one. This can be."""
    with pytest.raises(ValueError, match="must name what it stands in for"):
        Threshold(name="stale_after_days", days=90, fitted=False, stands_in_for=None)


def test_an_unfitted_threshold_with_an_empty_reason_is_also_refused() -> None:
    """An empty string is not a derivation. Otherwise the rule is satisfiable by typing ''."""
    with pytest.raises(ValueError, match="must name what it stands in for"):
        Threshold(name="stale_after_days", days=90, fitted=False, stands_in_for="")


def test_a_fitted_threshold_must_not_claim_to_stand_in_for_anything() -> None:
    """The other direction, and it prevents a STALE claim: a threshold that becomes fitted and
    keeps its old placeholder note now describes a substitution that no longer happens — the
    artifacts-falsified-by-progress pattern, refused at construction."""
    with pytest.raises(ValueError, match="stands in for nothing"):
        Threshold(name="stale_after_days", days=90, fitted=True, stands_in_for="a p90 gap")


def test_a_fitted_threshold_needs_no_reason() -> None:
    fitted = Threshold(name="stale_after_days", days=90, fitted=True, stands_in_for=None)
    assert fitted.fitted and fitted.stands_in_for is None


def test_dead_stocks_threshold_admits_it_is_a_constant_and_says_what_for() -> None:
    """D6, exercised. If this ever flips to fitted, the p90-gap capability must exist."""
    by_name = {threshold.name: threshold for threshold in DEAD_STOCK.thresholds}
    assert set(by_name) == {"stale_after_days", "expires_after_days", "feed_stale_after_days"}
    stale_after = by_name["stale_after_days"]
    assert stale_after.fitted is False
    assert stale_after.stands_in_for is not None
    # Not a one-word placeholder: it must say what the fitted version would compute.
    assert "p90" in stale_after.stands_in_for
    assert "PERCENTILE_CONT" in stale_after.stands_in_for


def test_every_dead_stock_threshold_is_an_admitted_constant() -> None:
    """THE RULE APPLIES TO ALL THREE, not to the one the test above happens to name. D6 is about
    unfitted numbers generally, and a per-threshold test would have to be written again for each
    new one, which is how the third arrives unchecked."""
    for threshold in DEAD_STOCK.thresholds:
        assert threshold.fitted is False, f"{threshold.name} claims to be fitted; D6 wants proof"
        assert threshold.stands_in_for, f"{threshold.name} is a constant that names nothing"


def test_a_declaration_cannot_carry_two_thresholds_with_the_same_name() -> None:
    """A LATENT TRAP INDEPENDENT OF ANY ONE ANALYSIS, and the failure it prevents is silent.

    Every consumer reads thresholds as a name-keyed mapping built with {t.name: t.days}, so a
    duplicate name does not raise, does not warn and does not render twice: the later entry
    simply WINS and the analysis runs on a number nobody chose. dead_stock is one keystroke from
    it, carrying stale_after_days=90 beside feed_stale_after_days=3 where the obvious name for
    the second was the first, which would have overwritten the 90 and changed the expiry
    arithmetic with no error anywhere.

    DUPLICATES ACROSS DECLARATIONS STAY LEGAL and already exist: stale_after_days means 90 days
    of no sale in dead_stock and 3 days of stale data in stockout_risk. That is why catalog.py
    keys its operator descriptions on (analysis_id, name).
    """
    duplicated = Threshold(
        name="stale_after_days", days=7, fitted=False, stands_in_for="a second one, deliberately"
    )
    with pytest.raises(ValueError, match="more than once"):
        replace(DEAD_STOCK, thresholds=(*DEAD_STOCK.thresholds, duplicated))


# ---------------------------------------------------------------------------
# Composition
# ---------------------------------------------------------------------------


def test_dead_stock_composes_two_capabilities() -> None:
    """And the composition is FORCED by the question, not chosen to exercise the contract.

    daily_series returns rows only for days that had sales, so a SKU that never sold produces
    no rows at all and the deadest stock is invisible to it. current_state is the universe of
    positions; last_sale_at is the subset that has ever sold; dead stock is the difference.
    """
    assert [r.capability_id for r in DEAD_STOCK.requires] == ["current_state", "last_sale_at"]


def test_the_two_required_capabilities_share_the_declarations_grain() -> None:
    """THE COMPOSITION RULE, and the first mechanical use of `grain` since it was extracted.

    Enforced for real at registry import (see test_registry); asserted here because this is the
    module that has to keep it true.
    """
    for descriptor in (CURRENT_STATE, LAST_SALE_AT):
        assert set(DEAD_STOCK.grain) <= set(descriptor.grain)


def test_every_field_dead_stock_reads_is_one_its_capability_returns() -> None:
    """The check that catches reaching for a plausible-but-absent field."""
    returns = {CURRENT_STATE.id: CURRENT_STATE.returns, LAST_SALE_AT.id: LAST_SALE_AT.returns}
    for requirement in DEAD_STOCK.requires:
        assert set(requirement.fields) <= set(returns[requirement.capability_id])


def test_dead_stock_does_not_read_last_source_event_at() -> None:
    """THE TRAP, PINNED AS A TEST.

    current_state returns `last_source_event_at`, which looks exactly like what dead stock
    needs and is not: canonical bumps it on ANY event-table row merged into the hot row, so a
    price change or an inventory adjustment refreshes it. A SKU dead for 200 days with a
    repricing yesterday would read as freshly moved.

    This is an assertion of ABSENCE, which is normally weak — but it is the specific absence
    someone optimising this later will try to remove, so it is worth a test that says no.
    """
    for requirement in DEAD_STOCK.requires:
        assert "last_source_event_at" not in requirement.fields, (
            "last_source_event_at is bumped by non-sale events; use last_sale_at instead"
        )


def test_dead_stock_needs_no_history_gate() -> None:
    """It works on sparse data BECAUSE absence is the signal — which is why it is the first
    declaration. One sale two years ago is a perfectly good last_sale_date."""
    assert all(requirement.gates == () for requirement in DEAD_STOCK.requires)


def test_a_requirement_naming_no_fields_is_refused() -> None:
    with pytest.raises(ValueError, match="names no fields"):
        CapabilityRequirement(capability_id="current_state", fields=(), gates=())


def test_an_analysis_requiring_nothing_is_refused() -> None:
    with pytest.raises(ValueError, match="requires no capability"):
        AnalysisDeclaration(
            id="empty",
            version="0.1.0",
            grain=("tenant_id",),
            requires=(),
            emits=("x",),
            holdout=None,
            thresholds=(),
        )


def test_an_analysis_requiring_the_same_capability_twice_is_refused() -> None:
    """Two requirements on one capability would need merging rules nobody has written."""
    requirement = CapabilityRequirement(capability_id="current_state", fields=("tenant_id",), gates=())
    with pytest.raises(ValueError, match="requires the same capability twice"):
        AnalysisDeclaration(
            id="twice",
            version="0.1.0",
            grain=("tenant_id",),
            requires=(requirement, requirement),
            emits=("x",),
            holdout=None,
            thresholds=(),
        )


def test_the_declaration_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        DEAD_STOCK.version = "9.9.9"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Contract fixture
# ---------------------------------------------------------------------------


def test_declaration_matches_the_committed_fixture() -> None:
    """The Python declaration and the contract fixture must not drift apart."""
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert fixture["id"] == DEAD_STOCK.id
    assert fixture["version"] == DEAD_STOCK.version
    assert tuple(fixture["grain"]) == DEAD_STOCK.grain
    assert tuple(fixture["emits"]) == DEAD_STOCK.emits
    assert [r["capability_id"] for r in fixture["requires"]] == [r.capability_id for r in DEAD_STOCK.requires]
    for wire, declared in zip(fixture["requires"], DEAD_STOCK.requires, strict=True):
        assert tuple(wire["fields"]) == declared.fields
        assert [g["kind"] for g in wire["gates"]] == [g.kind.value for g in declared.gates]
    wire_thresholds = {th["name"]: th for th in fixture["thresholds"]}
    for declared_threshold in DEAD_STOCK.thresholds:
        wire = wire_thresholds[declared_threshold.name]
        assert wire["days"] == declared_threshold.days
        assert wire["fitted"] == declared_threshold.fitted
        assert wire["stands_in_for"] == declared_threshold.stands_in_for

    # The holdout, which the fixture must carry because a declaration without one produces
    # unanalysable actions — and the fixture is what a consumer reads.
    holdout = DEAD_STOCK.holdout
    assert holdout is not None
    assert tuple(fixture["holdout"]["unit"]) == holdout.unit
    assert fixture["holdout"]["holdout_percent"] == holdout.holdout_percent
    assert fixture["holdout"]["salt"] == holdout.salt
    assert fixture["holdout"]["stands_in_for"] == holdout.stands_in_for


# ---------------------------------------------------------------------------
# Registry and contract must agree about which analyses exist
# ---------------------------------------------------------------------------


def test_every_declared_analysis_has_a_contract_fixture() -> None:
    """A DECLARATION WITH NO FIXTURE IS A CONTRACT NOBODY CHECKS.

    The conformance harness validates every fixture in the directory, so an analysis without one
    is simply absent from it — silently, because a harness that iterates cannot notice what is
    not there. This is the other direction, and it lives here rather than in validate.py because
    the registry is importable from Python and validate.py is deliberately JSON-only.
    """
    from pathlib import Path

    from synapse.registry import declared_analysis_ids

    fixtures = Path(__file__).resolve().parents[3] / "contracts" / "synapse" / "fixtures"
    on_disk = {path.stem for path in (fixtures / "analysis").glob("*.json")}
    assert set(declared_analysis_ids()) == on_disk, (
        "every declared analysis needs a fixture and vice versa; the harness validates what is "
        "on disk and cannot notice a declaration that never got one"
    )


def test_the_stockout_fixture_matches_the_declaration() -> None:
    """The same drift check dead_stock has, for the second analysis — including the two fields
    that are new in slice 7 and therefore have never been checked against a fixture before."""
    import json
    from pathlib import Path

    from synapse.core.analysis import STOCKOUT_RISK

    fixtures = Path(__file__).resolve().parents[3] / "contracts" / "synapse" / "fixtures"
    wire = json.loads((fixtures / "analysis" / "stockout_risk.json").read_text(encoding="utf-8"))

    assert wire["id"] == STOCKOUT_RISK.id
    assert wire["version"] == STOCKOUT_RISK.version
    assert tuple(wire["emits"]) == STOCKOUT_RISK.emits
    assert wire["max_rung"] == STOCKOUT_RISK.max_rung.value
    holdout = STOCKOUT_RISK.holdout
    assert holdout is not None
    assert wire["holdout"]["salt"] == holdout.salt

    by_id = {r["capability_id"]: r for r in wire["requires"]}
    for requirement in STOCKOUT_RISK.requires:
        on_wire = by_id[requirement.capability_id]
        assert tuple(on_wire["fields"]) == requirement.fields
        assert on_wire.get("window_from_threshold") == requirement.window_from_threshold
        assert [g["kind"] for g in on_wire["gates"]] == [g.kind.value for g in requirement.gates]
        assert [g["days"] for g in on_wire["gates"]] == [g.days for g in requirement.gates]
        assert [g["policy"] for g in on_wire["gates"]] == [g.policy.value for g in requirement.gates]


def test_the_two_analyses_use_independent_holdout_salts() -> None:
    """Concurrent experiments must randomise separately or they lose power together.

    The CONSEQUENCE — a SKU can be holdout for one and treatment for the other — is recorded in
    Holdout's docstring and in the declaration, with the trigger "the first analysis to leave
    shadow". It is harmless while nothing is delivered and is not this slice's to solve.
    """
    from synapse.core.analysis import DEAD_STOCK, STOCKOUT_RISK

    assert DEAD_STOCK.holdout is not None and STOCKOUT_RISK.holdout is not None
    assert DEAD_STOCK.holdout.salt != STOCKOUT_RISK.holdout.salt
