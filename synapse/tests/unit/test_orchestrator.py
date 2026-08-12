"""The orchestrator, offline: the plan indirection, the rung refusal, and as_of == slot.

WHAT IS TESTABLE WITHOUT A DATABASE, and it is more than it looks. The sweep itself needs two
engines, but the three properties most likely to go silently wrong do not:

  - ``as_of`` IS THE SLOT. If this ever became a second clock read, a retry after midnight would
    compute a different as_of, uq_actions_idempotency would correctly decide the actions were
    different, and a full duplicate set would land. That is the event-sink failure this project
    has already been bitten by twice, and it is checked here rather than in a staging window.
  - THE RUNG REFUSAL. Nothing delivers anything, so any rung above SHADOW must be refused
    outright rather than quietly run as shadow.
  - THE PLAN INVARIANT. An analysis that proposes actions with no plan would resolve, produce
    nothing, and be indistinguishable from a tenant with no findings.

The live suite only runs inside a staging window, so a guard reachable only from there is a
guard that lags by however long the gap is. These are the ones that should not wait.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import UUID

import pytest

from synapse.core.analysis import DEAD_STOCK
from synapse.core.capability import CURRENT_STATE, LAST_SALE_AT
from synapse.core.current_state import CurrentStateRow
from synapse.core.declaration_resolution import DeclarationSatisfied
from synapse.core.holdout import Arm
from synapse.core.last_sale_at import LastSaleAtRow
from synapse.core.provision import Cadence, Provision, Rung
from synapse.core.refusal import RefusalReason
from synapse.core.resolution import Satisfied
from synapse.orchestrator.runner import SlotResult, _propose, _run_one, summarise

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a161")


def _position(sku_id: str) -> CurrentStateRow:
    return CurrentStateRow(
        tenant_id=TENANT,
        store_id=STORE,
        sku_id=sku_id,
        product_name=f"Product {sku_id}",
        product_category=None,
        sku_status="ACTIVE",
        current_retail_price=Decimal("89.0000"),
        unit_cost=None,
        promo_price=None,
        stock_qty=Decimal("7.000"),
        reorder_point=None,
        currency="INR",
        expiry_date=None,
        last_source_event_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
        last_updated_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
    )


def _fresh_feed(slot: date) -> LastSaleAtRow:
    """A sale on the slot itself, for a SKU that is never in the universe.

    dead_stock refuses the whole sweep when the tenant has no sale history, because with nothing
    in `selling` every position reads as never-sold and a catalogue of findings is really one
    statement about the feed. Every test in this file is about the SLOT reaching provenance and
    the expiry, so each needs a tenant whose feed is current on that slot; without this they
    would silently become tests of the feed refusal. Dated on the slot rather than on a constant
    so the tests that use a 2020 slot stay fresh relative to their own as_of.
    """
    return LastSaleAtRow(tenant_id=TENANT, store_id=STORE, sku_id="FEED_ANCHOR", last_sale_date=slot)


def _satisfied(universe: Sequence[CurrentStateRow], selling: Sequence[LastSaleAtRow]) -> Any:
    """A real ``DeclarationSatisfied`` over bound fetches that return fixed rows.

    Built from the ACTUAL descriptors and the ACTUAL declaration rather than stubs, so the
    capability versions that reach provenance are the real ones — a stub would let this test
    pass while provenance carried a version nothing had.
    """

    async def _universe() -> Sequence[CurrentStateRow]:
        return universe

    async def _selling() -> Sequence[LastSaleAtRow]:
        return selling

    return DeclarationSatisfied(
        declaration=DEAD_STOCK,
        resolutions={
            "current_state": Satisfied(descriptor=CURRENT_STATE, fetch=_universe),
            "last_sale_at": Satisfied(descriptor=LAST_SALE_AT, fetch=_selling),
        },
    )


def _provision(**overrides: object) -> Provision:
    fields: dict[str, object] = {
        "tenant_id": TENANT,
        "analysis_id": "dead_stock",
        "cadence": Cadence.DAILY,
        "rung": Rung.SHADOW,
        "timezone": "Asia/Kolkata",
        "enabled_at": datetime(2026, 8, 1, tzinfo=UTC),
    }
    fields.update(overrides)
    return Provision(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# as_of IS the slot — the property the idempotency index depends on
# ---------------------------------------------------------------------------


async def test_every_action_is_stamped_with_the_slot_not_todays_date() -> None:
    """THE LOAD-BEARING ASSERTION OF THIS SLICE.

    ``uq_actions_idempotency`` includes ``as_of``. A retry that recomputed as_of from the clock
    would produce actions the index considers DIFFERENT and would append a full duplicate set —
    the same class of failure as the event sink and the CSV path, both of which this project has
    already paid for.

    The slot here is deliberately NOT today: if the implementation reached for date.today() this
    assertion fails on every day except one.
    """
    slot = date(2020, 1, 2)
    actions = (await _propose(_satisfied([_position("SKU-DEAD")], [_fresh_feed(slot)]), slot)).actions

    assert actions, "a position that never sold is dead stock; the fixture must produce one"
    assert {action.provenance.as_of for action in actions} == {slot}


async def test_the_expiry_is_derived_from_the_slot_too() -> None:
    """expires_on is inside the payload hash, so it has the same requirement as as_of: derived
    from the slot, never from the clock. Otherwise a retry hashes differently and duplicates."""
    slot = date(2020, 1, 2)
    actions = (await _propose(_satisfied([_position("SKU-DEAD")], [_fresh_feed(slot)]), slot)).actions
    expires_after = next(t for t in DEAD_STOCK.thresholds if t.name == "expires_after_days")
    assert {action.expires_on for action in actions} == {slot + timedelta(days=expires_after.days)}


async def test_two_runs_of_the_same_slot_propose_identical_actions() -> None:
    """WHY THE INDEX CAN SUPPRESS A RETRY AT ALL. Every field in the payload hash — quantity,
    expiry, arm, versions, thresholds — must come out the same for one slot. Running the plan
    twice and comparing is the honest check; asserting the hash would be reimplementing it.
    """
    slot = date(2026, 8, 5)
    first = await _propose(_satisfied([_position("SKU-DEAD")], [_fresh_feed(slot)]), slot)
    second = await _propose(_satisfied([_position("SKU-DEAD")], [_fresh_feed(slot)]), slot)
    assert first == second


async def test_a_different_slot_proposes_different_actions() -> None:
    """The converse, and it is what stops the test above passing against a constant. A genuinely
    new day is a new action, which the index must NOT suppress."""
    universe = [_position("SKU-DEAD")]
    first_slot, second_slot = date(2026, 8, 5), date(2026, 8, 6)
    first = await _propose(_satisfied(universe, [_fresh_feed(first_slot)]), first_slot)
    second = await _propose(_satisfied(universe, [_fresh_feed(second_slot)]), second_slot)
    assert first != second
    # AND BOTH ACTUALLY PROPOSED. Two empty results are also unequal in no useful way, and a feed
    # refusal on either side would satisfy the assertion above while proving nothing about slots.
    assert first.actions and second.actions


async def test_every_proposed_action_carries_an_arm_and_full_provenance() -> None:
    """D2. An action without an arm can never be analysed and the counterfactual cannot be added
    later; one without capability versions cannot be compared across a version change."""
    slot = date(2026, 8, 5)
    actions = (await _propose(_satisfied([_position("SKU-DEAD")], [_fresh_feed(slot)]), slot)).actions
    for action in actions:
        assert action.arm in (Arm.TREATMENT, Arm.HOLDOUT)
        assert action.provenance.declaration_id == "dead_stock"
        assert action.provenance.declaration_version == DEAD_STOCK.version
        assert set(action.provenance.capability_versions) == {"current_state", "last_sale_at"}
        assert action.provenance.thresholds


# ---------------------------------------------------------------------------
# The rung refusal — a guard that must fire before anything is claimed
# ---------------------------------------------------------------------------


async def test_a_rung_above_shadow_is_refused_without_touching_a_database() -> None:
    """NOTHING DELIVERS ANYTHING, so 'suggest' is a promise the build cannot keep.

    Both engines are None, which is the assertion: the refusal must happen BEFORE a run is
    claimed or a connection opened. If the check ever moved below the claim, this raises
    AttributeError instead of returning, and the test fails rather than passing quietly.
    """
    result = await _run_one(
        provision=_provision(rung=Rung.SUGGEST),
        reader_engine=None,  # type: ignore[arg-type]
        writer_engine=None,  # type: ignore[arg-type]
        now=datetime(2026, 8, 5, 3, 30, tzinfo=UTC),
        dry_run=False,
    )
    assert result.outcome == "failed"
    assert result.actions_appended == 0
    assert result.detail is not None and "nothing implements it" in result.detail


async def test_the_refusal_still_reports_the_slot_it_would_have_run() -> None:
    """An operator seeing a refused pair needs to know which slot was skipped, or the gap in the
    denominator is unexplained."""
    result = await _run_one(
        provision=_provision(rung=Rung.SUGGEST),
        reader_engine=None,  # type: ignore[arg-type]
        writer_engine=None,  # type: ignore[arg-type]
        now=datetime(2026, 8, 4, 21, 30, tzinfo=UTC),  # 03:00 IST on the 5th
        dry_run=False,
    )
    assert result.slot == date(2026, 8, 5)


# ---------------------------------------------------------------------------
# The plan invariant
# ---------------------------------------------------------------------------


def test_every_analysis_that_proposes_actions_has_a_plan() -> None:
    """The registry checks this at import; this states the property so it is greppable.

    A proposer with no plan resolves, produces nothing, and looks exactly like a tenant with no
    findings — the confusion synapse.run exists to prevent, reintroduced one layer up.
    """
    from synapse.registry import _ACTIONS, _PLANS

    assert set(_ACTIONS) <= set(_PLANS)


def test_the_plan_check_bites_when_a_proposer_has_no_plan() -> None:
    """PROVE THE GUARD FIRES, by constructing the violation rather than patching the registry.

    ``_PLANS`` is Final; reassigning it is a type error and mutating it would corrupt every test
    that ran afterwards. The pure function takes the maps, so the illegal combination is just an
    argument.
    """
    from synapse.registry import check_plan_bindings

    with pytest.raises(ValueError, match="no plan"):
        check_plan_bindings({}, {"dead_stock": lambda *a, **k: []}, {"dead_stock": DEAD_STOCK})


def test_the_plan_check_bites_on_a_plan_with_no_declaration() -> None:
    from synapse.registry import PlanResult, check_plan_bindings

    async def _plan(*args: object, **kwargs: object) -> PlanResult:
        return PlanResult(actions=(), refusals={})

    with pytest.raises(ValueError, match="no declaration"):
        check_plan_bindings({"invented": _plan}, {}, {})


def test_the_plan_check_accepts_the_real_registry() -> None:
    """The baseline. Without it the two refusals above would also pass against a function that
    raised unconditionally."""
    from synapse.registry import _ACTIONS, _DECLARATIONS, _PLANS, check_plan_bindings

    check_plan_bindings(_PLANS, _ACTIONS, _DECLARATIONS)


def test_plan_for_returns_none_rather_than_raising_for_an_unknown_id() -> None:
    """A declaration may legitimately have no proposer, so absence is an answer, not an error."""
    from synapse.registry import plan_for

    assert plan_for("no_such_analysis") is None


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------


def test_summarise_counts_skipped_separately_from_outcomes() -> None:
    """A skipped slot has NO outcome — there is no run to have one — so counting it under None
    would read as a missing value rather than a deliberate no-op."""
    results = [
        SlotResult(TENANT, "dead_stock", date(2026, 8, 5), "satisfied", 3, 3),
        SlotResult(TENANT, "dead_stock", date(2026, 8, 5), None, 0, 0, skipped=True),
        SlotResult(TENANT, "dead_stock", date(2026, 8, 5), "failed", 0, 0),
    ]
    assert dict(summarise(results)) == {"satisfied": 1, "skipped": 1, "failed": 1}


def test_failed_is_derived_rather_than_stored_twice() -> None:
    assert SlotResult(TENANT, "a", date(2026, 8, 5), "failed", 0, 0).failed
    assert not SlotResult(TENANT, "a", date(2026, 8, 5), "satisfied", 1, 1).failed


# ---------------------------------------------------------------------------
# THE REFUSAL REACHES THE RUN ROW (Part 2's condition)
# ---------------------------------------------------------------------------
#
# A stale tenant producing NOTHING is indistinguishable from a healthy tenant with no dead
# stock. These assert on the PLAN's return value, which is the shape runner._run_one writes into
# synapse.run.refusals, so what is checked here is what an operator reads.


async def test_a_stale_tenant_produces_a_refusal_rather_than_silence() -> None:
    """PART 2's WHOLE CONDITION. The count is per POSITION, so an operator sees how much of the
    catalogue went unassessed rather than only that something did."""
    slot = date(2026, 8, 5)
    stale = LastSaleAtRow(
        tenant_id=TENANT, store_id=STORE, sku_id="OLD", last_sale_date=slot - timedelta(days=30)
    )
    universe = [_position("SKU-A"), _position("SKU-B")]

    result = await _propose(_satisfied(universe, [stale]), slot)

    assert result.actions == []
    assert result.refusals == {RefusalReason.FEED_STALE: 2}


async def test_a_tenant_with_no_sale_history_produces_a_refusal_rather_than_a_catalogue() -> None:
    """THE STAGING CASE. With no sale history every position reads as never-sold, which used to
    make the entire catalogue dead stock on the first sweep: 38 alerts, all with a NULL age, none
    aged past the threshold. It is now one refusal per position and no actions at all."""
    slot = date(2026, 8, 5)
    universe = [_position("SKU-A"), _position("SKU-B"), _position("SKU-C")]

    result = await _propose(_satisfied(universe, []), slot)

    assert result.actions == []
    assert result.refusals == {RefusalReason.NO_SALE_HISTORY: 3}


async def test_the_stock_premise_reaches_the_run_row_too() -> None:
    """32 OF STAGING'S 38 ALERTS FAILED THIS PREMISE, and under a skip they would have vanished
    with no record. The two reasons stay separate because they send an operator to different
    places: no figure arrived is an ingestion problem, none on hand is not."""
    slot = date(2026, 8, 5)
    universe = [
        replace(_position("NO-FIGURE"), stock_qty=None),
        replace(_position("ZERO"), stock_qty=Decimal("0")),
        _position("REAL"),
    ]

    result = await _propose(_satisfied(universe, [_fresh_feed(slot)]), slot)

    assert result.refusals == {
        RefusalReason.NO_STOCK_QUANTITY: 1,
        RefusalReason.NO_STOCK_ON_HAND: 1,
    }
    # THE VACUITY GUARD: the position that satisfies the premise still produces its action, so a
    # premise check that refused everything cannot pass this.
    assert [a.target["sku_id"] for a in result.actions] == ["REAL"]


async def test_a_healthy_run_still_records_no_refusals() -> None:
    """The other direction. An empty map must keep meaning "this run refused nothing", which is
    the reading PlanResult's docstring now commits to for every analysis."""
    slot = date(2026, 8, 5)

    result = await _propose(_satisfied([_position("SKU-DEAD")], [_fresh_feed(slot)]), slot)

    assert result.refusals == {}
    assert result.actions
