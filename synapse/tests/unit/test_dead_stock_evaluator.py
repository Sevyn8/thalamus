"""The dead_stock evaluator, offline. Pure arithmetic — no DB, no engine, no registry.

THE LOAD-BEARING TESTS ARE THE BOUNDARY AND THE NEVER-SOLD CASE.

- The boundary because an off-by-one silently moves the whole answer by one day's worth of SKUs,
  and nobody notices a count that is plausible.
- Never-sold because it is the strongest signal in the analysis and the easiest to get wrong: a
  position absent from last_sale_at must come back dead with ``days_since_last_sale=None``, not
  be skipped, and not be given a fabricated large number.

Plus one test that pins a DELIBERATE BLIND SPOT: a selling position outside the universe is
invisible here. That is by design (the universe is authoritative) and it is why the subset claim
has its own live test — but a blind spot nobody wrote down is indistinguishable from a bug.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from synapse.core.analysis import DEAD_STOCK
from synapse.core.current_state import CurrentStateRow
from synapse.core.dead_stock import DeadStockRow, evaluate_dead_stock
from synapse.core.last_sale_at import LastSaleAtRow
from synapse.core.refusal import RefusalReason

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
AS_OF = date(2026, 8, 5)
STALE_AFTER = 90
FEED_STALE_AFTER = 3


# A SALE THAT KEEPS THE TENANT'S FEED FRESH, for every test that is not about the feed.
#
# WHY IT IS NEEDED AT ALL, since it did not used to be: the evaluator refuses the whole sweep
# when the tenant has NO sale history, because with nothing in `selling` every position reads as
# never-sold and a catalogue of findings is really one statement about the feed. So a test whose
# subject is "this position never sold" must give the tenant some OTHER sale, or it is testing
# the feed refusal instead of the thing it names. It is a separate SKU that is never in the
# universe, which the invisible-orphan test already pins as harmless.
def _fresh_feed() -> list[LastSaleAtRow]:
    return [_sold("FEED_ANCHOR", AS_OF)]


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


def _sold(sku_id: str, when: date) -> LastSaleAtRow:
    return LastSaleAtRow(tenant_id=TENANT, store_id=STORE, sku_id=sku_id, last_sale_date=when)


def _position_without_stock(sku_id: str, stock_qty: Decimal | None) -> CurrentStateRow:
    return replace(_position(sku_id), stock_qty=stock_qty)


def _evaluate(universe: list[CurrentStateRow], selling: list[LastSaleAtRow]) -> dict[str, DeadStockRow]:
    """Evaluate with a FRESH FEED unless the caller supplied sales of its own.

    The anchor is appended rather than substituted, so a test that passes its own `selling` still
    gets a tenant whose feed is current and is therefore testing the position-level rule it
    names.
    """
    rows = evaluate_dead_stock(
        universe,
        [*selling, *_fresh_feed()],
        stale_after_days=STALE_AFTER,
        feed_stale_after_days=FEED_STALE_AFTER,
        as_of=AS_OF,
    )
    return {row.sku_id: row for row in rows}


# ---------------------------------------------------------------------------
# The boundary
# ---------------------------------------------------------------------------


def test_exactly_the_threshold_is_dead() -> None:
    """``>=``, inclusive. Tested because an off-by-one here moves the answer by a day's worth of
    SKUs and the resulting count is entirely plausible."""
    by_sku = _evaluate([_position("A")], [_sold("A", AS_OF - timedelta(days=90))])
    assert by_sku["A"].days_since_last_sale == 90
    assert by_sku["A"].is_dead_stock is True


def test_one_day_inside_the_threshold_is_alive() -> None:
    by_sku = _evaluate([_position("A")], [_sold("A", AS_OF - timedelta(days=89))])
    assert by_sku["A"].days_since_last_sale == 89
    assert by_sku["A"].is_dead_stock is False


def test_one_day_past_the_threshold_is_dead() -> None:
    by_sku = _evaluate([_position("A")], [_sold("A", AS_OF - timedelta(days=91))])
    assert by_sku["A"].days_since_last_sale == 91
    assert by_sku["A"].is_dead_stock is True


def test_a_sale_today_is_zero_days_and_alive() -> None:
    by_sku = _evaluate([_position("A")], [_sold("A", AS_OF)])
    assert by_sku["A"].days_since_last_sale == 0
    assert by_sku["A"].is_dead_stock is False


# ---------------------------------------------------------------------------
# Never sold
# ---------------------------------------------------------------------------


def test_a_position_that_never_sold_is_dead_with_none_days() -> None:
    """THE STRONGEST SIGNAL IN THE ANALYSIS. An absent row means no sale in the tenant's entire
    history — deader than any number — and it must come back as a row rather than be skipped."""
    by_sku = _evaluate([_position("A")], [])
    assert by_sku["A"].days_since_last_sale is None
    assert by_sku["A"].is_dead_stock is True


def test_none_distinguishes_never_sold_from_long_ago() -> None:
    """Both are dead; they are different problems (a buyer's and a merchandiser's), and ``None``
    is the only thing that tells them apart."""
    by_sku = _evaluate(
        [_position("NEVER"), _position("STALE")], [_sold("STALE", AS_OF - timedelta(days=200))]
    )
    assert by_sku["NEVER"].days_since_last_sale is None
    assert by_sku["STALE"].days_since_last_sale == 200
    assert by_sku["NEVER"].is_dead_stock and by_sku["STALE"].is_dead_stock


# ---------------------------------------------------------------------------
# Shape and the deliberate blind spot
# ---------------------------------------------------------------------------


def test_it_emits_one_row_per_position_not_only_the_dead_ones() -> None:
    """If it emitted only dead rows, ``is_dead_stock`` would never vary and would carry no
    information. Emitting the universe also makes "12 of 66" sayable instead of "12"."""
    rows = evaluate_dead_stock(
        [_position("A"), _position("B"), _position("C")],
        [_sold("A", AS_OF), _sold("B", AS_OF - timedelta(days=200))],
        stale_after_days=STALE_AFTER,
        feed_stale_after_days=FEED_STALE_AFTER,
        as_of=AS_OF,
    )
    assert len(rows) == 3
    assert sum(row.is_dead_stock for row in rows) == 2  # B stale, C never sold


def test_a_selling_position_outside_the_universe_is_invisible() -> None:
    """A DELIBERATE BLIND SPOT, pinned so it is designed rather than accidental.

    The universe is authoritative — a position that does not exist cannot be dead stock — so a
    row in ``selling`` with no matching position produces nothing and raises nothing. That is
    also exactly the under-reporting hazard the subset claim guards, which is why it has a live
    test: the evaluator cannot detect a bad universe from inside itself.
    """
    rows = evaluate_dead_stock(
        [_position("A")],
        [_sold("A", AS_OF), _sold("ORPHAN", AS_OF)],
        stale_after_days=STALE_AFTER,
        feed_stale_after_days=FEED_STALE_AFTER,
        as_of=AS_OF,
    )
    assert [row.sku_id for row in rows] == ["A"]


def test_an_empty_universe_evaluates_to_nothing() -> None:
    """Not an error. A tenant with no positions has no dead stock, which is a true answer."""
    assert (
        evaluate_dead_stock(
            [], [], stale_after_days=STALE_AFTER, feed_stale_after_days=FEED_STALE_AFTER, as_of=AS_OF
        )
        == []
    )


def test_a_future_dated_sale_is_not_dead_and_is_not_clamped() -> None:
    """canonical's event_date is source-supplied, so a clock-skewed POS can date a sale tomorrow.
    Negative days pass through: it is plainly not stale, and clamping to zero would hide the
    skew from whoever needs to see it."""
    by_sku = _evaluate([_position("A")], [_sold("A", AS_OF + timedelta(days=3))])
    assert by_sku["A"].days_since_last_sale == -3
    assert by_sku["A"].is_dead_stock is False


def test_a_nonsense_threshold_is_refused() -> None:
    with pytest.raises(ValueError, match="stale_after_days must be at least 1 day"):
        evaluate_dead_stock([], [], stale_after_days=0, feed_stale_after_days=FEED_STALE_AFTER, as_of=AS_OF)


def test_a_nonsense_feed_threshold_is_refused() -> None:
    """The second threshold gets the same guard as the first. A zero here would refuse every
    tenant whose newest sale is not from the future."""
    with pytest.raises(ValueError, match="feed_stale_after_days must be at least 1 day"):
        evaluate_dead_stock([], [], stale_after_days=STALE_AFTER, feed_stale_after_days=0, as_of=AS_OF)


# ---------------------------------------------------------------------------
# The declaration
# ---------------------------------------------------------------------------


def test_the_row_matches_the_declarations_emits() -> None:
    """Enforced at registry import too; asserted here because this is the module that must keep
    it true. The declaration's promise about what it produces must BE what the code produces."""
    assert set(DeadStockRow.__dataclass_fields__) == set(DEAD_STOCK.emits)


def test_the_threshold_the_declaration_carries_is_the_one_the_evaluator_takes() -> None:
    """stale_after_days is a threshold, not a gate: no read depends on it, and it is the whole
    content of the rule. The evaluator takes it as a parameter rather than reading the
    declaration, so the arithmetic stays pure and testable at any value."""
    threshold = next(t for t in DEAD_STOCK.thresholds if t.name == "stale_after_days")
    by_sku = {
        row.sku_id: row
        for row in evaluate_dead_stock(
            [_position("A")],
            [_sold("A", AS_OF - timedelta(days=threshold.days)), *_fresh_feed()],
            stale_after_days=threshold.days,
            feed_stale_after_days=FEED_STALE_AFTER,
            as_of=AS_OF,
        )
    }
    assert by_sku["A"].is_dead_stock is True


# ---------------------------------------------------------------------------
# THE DECLARATION'S OWN PREMISE: stock on hand that is not selling
# ---------------------------------------------------------------------------
#
# Until this slice the declaration asserted this in a comment and nothing honoured it. Measured
# on staging 2026-08-12: of 38 dead-stock alerts, 20 carried NO stock figure and 12 carried zero,
# so 32 of 38 contradicted the premise the declaration claimed.


def test_a_position_with_no_stock_figure_is_refused_not_flagged() -> None:
    """1a. NULL means no figure arrived, so "stock on hand but not selling" cannot be satisfied.

    REFUSED RATHER THAN SKIPPED, and that is the whole shape of this change. A skipped position
    produces no row anywhere, so 20 of staging's 38 would have vanished with no record and the
    run would read "0 alerts, 0 refusals", which is the silent nothing this slice exists to remove.
    """
    by_sku = _evaluate([_position_without_stock("A", None)], [])

    assert by_sku["A"].is_dead_stock is False
    assert by_sku["A"].refusal_reason is RefusalReason.NO_STOCK_QUANTITY
    assert by_sku["A"].refused_because is not None
    assert "NULL is not zero" in by_sku["A"].refused_because


def test_a_position_with_zero_stock_is_refused_not_flagged() -> None:
    """1b, AND IT IS A RULING RATHER THAN AN OVERSIGHT, which is why it has its own test.

    A recorded zero means a figure arrived saying none on hand. It differs from NULL in
    PROVENANCE and is identical in what an operator can do about it, which is nothing: there is
    no stock to review, mark down, move or write off. The declaration's justification, "dead
    stock with no stock is not a problem to solve", covers both without distinction.
    """
    by_sku = _evaluate([_position_without_stock("A", Decimal("0"))], [])

    assert by_sku["A"].is_dead_stock is False
    assert by_sku["A"].refusal_reason is RefusalReason.NO_STOCK_ON_HAND


def test_zero_and_null_stay_two_different_reasons() -> None:
    """THE STORED BREAKDOWN IS WHAT AN OPERATOR READS WHEN A CATALOGUE GOES QUIET, and the two
    send them to different places: no figure arrived is an ingestion problem, none on hand is
    not. Merging the keys would destroy that distinction for ever, because nothing migrates a
    JSONB key."""
    by_sku = _evaluate(
        [_position_without_stock("NULL", None), _position_without_stock("ZERO", Decimal("0"))], []
    )

    assert by_sku["NULL"].refusal_reason is not by_sku["ZERO"].refusal_reason


def test_a_negative_stock_figure_is_refused_with_zero() -> None:
    """A negative is a real value in that column and is not stock on hand under any reading."""
    by_sku = _evaluate([_position_without_stock("A", Decimal("-4"))], [])

    assert by_sku["A"].refusal_reason is RefusalReason.NO_STOCK_ON_HAND


def test_a_position_with_stock_is_still_flagged() -> None:
    """THE VACUITY GUARD for the four above. A premise check that refused everything would make
    all of them pass while the analysis produced nothing at all, for ever."""
    by_sku = _evaluate([_position("A")], [_sold("A", AS_OF - timedelta(days=200))])

    assert by_sku["A"].is_dead_stock is True
    assert by_sku["A"].refusal_reason is None


# ---------------------------------------------------------------------------
# THE FEED REFUSAL: a stalled feed must not manufacture a catalogue of findings
# ---------------------------------------------------------------------------


def test_a_tenant_that_has_never_sold_is_refused_rather_than_wholly_dead() -> None:
    """THE CASE THAT PRODUCED EVERY ALERT IN STAGING. All 38 carried a NULL age and not one was
    aged past the threshold, which is what "the tenant has sent nothing" looks like from inside.

    With no sale history every position is absent from `selling` and reads as never-sold, so the
    whole catalogue becomes dead stock on the first sweep. That is one statement about the feed,
    not a finding per product.
    """
    rows = evaluate_dead_stock(
        [_position("A"), _position("B")],
        [],
        stale_after_days=STALE_AFTER,
        feed_stale_after_days=FEED_STALE_AFTER,
        as_of=AS_OF,
    )

    assert [row.is_dead_stock for row in rows] == [False, False]
    assert {row.refusal_reason for row in rows} == {RefusalReason.NO_SALE_HISTORY}


def test_a_stale_feed_produces_a_refusal_rather_than_silence() -> None:
    """2b, AND IT IS THE CONDITION ON THE WHOLE FEED CHECK. A stale tenant producing NOTHING is
    indistinguishable from a healthy tenant with no dead stock, which is why the refusal exists
    rather than an early return."""
    rows = evaluate_dead_stock(
        [_position("A")],
        [_sold("A", AS_OF - timedelta(days=FEED_STALE_AFTER + 1))],
        stale_after_days=STALE_AFTER,
        feed_stale_after_days=FEED_STALE_AFTER,
        as_of=AS_OF,
    )

    assert len(rows) == 1
    assert rows[0].is_dead_stock is False
    assert rows[0].refusal_reason is RefusalReason.FEED_STALE
    assert rows[0].refused_because is not None


def test_the_feed_boundary_is_strictly_greater() -> None:
    """EXACTLY THE THRESHOLD IS STILL FRESH, and the asymmetry with stale_after_days above is
    deliberate. Three other places ask this same question with strictly greater: stockout_risk's
    staleness refusal, orchestrator/freshness.py and the fleet roster's column. A fourth
    convention would make two screens disagree about a tenant sitting on the boundary."""
    at_the_line = evaluate_dead_stock(
        [_position("A")],
        [_sold("A", AS_OF - timedelta(days=FEED_STALE_AFTER))],
        stale_after_days=STALE_AFTER,
        feed_stale_after_days=FEED_STALE_AFTER,
        as_of=AS_OF,
    )
    assert at_the_line[0].refusal_reason is None

    one_past = evaluate_dead_stock(
        [_position("A")],
        [_sold("A", AS_OF - timedelta(days=FEED_STALE_AFTER + 1))],
        stale_after_days=STALE_AFTER,
        feed_stale_after_days=FEED_STALE_AFTER,
        as_of=AS_OF,
    )
    assert one_past[0].refusal_reason is RefusalReason.FEED_STALE


def test_the_feed_verdict_outranks_the_stock_premise() -> None:
    """ORDERED MOST-FUNDAMENTAL FIRST, the discipline stockout_risk's _refusal already states.
    A position that is both on a dead feed and missing its stock figure is reported as the feed,
    because restoring the feed may resolve both while fixing one stock figure resolves neither.
    """
    rows = evaluate_dead_stock(
        [_position_without_stock("A", None)],
        [_sold("OTHER", AS_OF - timedelta(days=FEED_STALE_AFTER + 1))],
        stale_after_days=STALE_AFTER,
        feed_stale_after_days=FEED_STALE_AFTER,
        as_of=AS_OF,
    )

    assert rows[0].refusal_reason is RefusalReason.FEED_STALE


def test_a_refused_row_still_carries_its_age() -> None:
    """The age is a fact about the position and is knowable whether or not the premise held.
    Dropping it would make a refused row less useful to whoever is diagnosing the outage."""
    rows = evaluate_dead_stock(
        [_position_without_stock("A", None)],
        [_sold("A", AS_OF - timedelta(days=200)), *_fresh_feed()],
        stale_after_days=STALE_AFTER,
        feed_stale_after_days=FEED_STALE_AFTER,
        as_of=AS_OF,
    )

    assert rows[0].days_since_last_sale == 200
    assert rows[0].is_dead_stock is False


def test_a_refusal_can_never_be_flagged_dead() -> None:
    """The invariant, asserted on the type rather than trusted to every branch. A refusal is not
    a verdict, and an action must never come from one."""
    with pytest.raises(ValueError, match="refusal is not a verdict"):
        DeadStockRow(
            tenant_id=TENANT,
            store_id=STORE,
            sku_id="A",
            days_since_last_sale=None,
            is_dead_stock=True,
            refused_because="anything",
            refusal_reason=RefusalReason.FEED_STALE,
        )


def test_a_row_cannot_carry_prose_without_a_category() -> None:
    """The two halves are pinned to each other, so a stored breakdown and the row a reader opens
    can never disagree about whether a position was assessed."""
    with pytest.raises(ValueError, match="must carry BOTH"):
        DeadStockRow(
            tenant_id=TENANT,
            store_id=STORE,
            sku_id="A",
            days_since_last_sale=None,
            is_dead_stock=False,
            refused_because="prose with no category",
        )
