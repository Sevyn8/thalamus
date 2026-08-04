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

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from synapse.core.analysis import DEAD_STOCK
from synapse.core.current_state import CurrentStateRow
from synapse.core.dead_stock import DeadStockRow, evaluate_dead_stock
from synapse.core.last_sale_at import LastSaleAtRow

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
AS_OF = date(2026, 8, 5)
STALE_AFTER = 90


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


def _evaluate(
    universe: list[CurrentStateRow], selling: list[LastSaleAtRow]
) -> dict[str, DeadStockRow]:
    rows = evaluate_dead_stock(
        universe, selling, stale_after_days=STALE_AFTER, as_of=AS_OF
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
        as_of=AS_OF,
    )
    assert [row.sku_id for row in rows] == ["A"]


def test_an_empty_universe_evaluates_to_nothing() -> None:
    """Not an error. A tenant with no positions has no dead stock, which is a true answer."""
    assert evaluate_dead_stock([], [], stale_after_days=STALE_AFTER, as_of=AS_OF) == []


def test_a_future_dated_sale_is_not_dead_and_is_not_clamped() -> None:
    """canonical's event_date is source-supplied, so a clock-skewed POS can date a sale tomorrow.
    Negative days pass through: it is plainly not stale, and clamping to zero would hide the
    skew from whoever needs to see it."""
    by_sku = _evaluate([_position("A")], [_sold("A", AS_OF + timedelta(days=3))])
    assert by_sku["A"].days_since_last_sale == -3
    assert by_sku["A"].is_dead_stock is False


def test_a_nonsense_threshold_is_refused() -> None:
    with pytest.raises(ValueError, match="at least 1 day"):
        evaluate_dead_stock([], [], stale_after_days=0, as_of=AS_OF)


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
            [_sold("A", AS_OF - timedelta(days=threshold.days))],
            stale_after_days=threshold.days,
            as_of=AS_OF,
        )
    }
    assert by_sku["A"].is_dead_stock is True
