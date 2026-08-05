"""The second analysis: days of cover, and the four reasons there is sometimes none.

WHAT THIS FILE IS REALLY TESTING. `stockout_risk` exists to break whatever a single example got
wrong, so the assertions here fall into two groups: the arithmetic, and the REFUSALS. The
refusals matter more. Every one of them is a case where a number could have been produced and
would have been wrong, and the whole design rests on preferring "we cannot tell" to a confident
figure.

NO TEST HERE RECOMPUTES A RATE. Asserting `cover == stock / (total / window)` would be the same
arithmetic twice and would pass with both copies wrong; every expected value below is one a
human worked out from inputs chosen to make it obvious.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from synapse.core.current_state import CurrentStateRow
from synapse.core.daily_series import DailySeriesRow
from synapse.core.stockout_risk import (
    StockoutRiskRow,
    counts_by_reason,
    evaluate_stockout_risk,
)

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
AS_OF = date(2026, 8, 5)

# Defaults chosen so each test varies ONE thing. 28-day window, 14-day risk line, 3-day
# staleness limit, 7 observations required — the declaration's real numbers.
WINDOW = 28
AT_RISK = 14
STALE = 3
MIN_OBS = 7


def _position(sku_id: str = "SKU-1", stock: str | None = "70.000") -> CurrentStateRow:
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
        stock_qty=None if stock is None else Decimal(stock),
        reorder_point=None,
        currency="INR",
        expiry_date=None,
        last_source_event_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
        last_updated_at=datetime(2026, 8, 4, 9, 0, tzinfo=UTC),
    )


def _day(offset: int, quantity: str, sku_id: str = "SKU-1") -> DailySeriesRow:
    """One day's movement, ``offset`` days before AS_OF."""
    return DailySeriesRow(
        tenant_id=TENANT,
        store_id=STORE,
        sku_id=sku_id,
        event_date=date.fromordinal(AS_OF.toordinal() - offset),
        net_quantity=Decimal(quantity),
        sale_line_count=1,
        return_line_count=0,
        void_line_count=0,
    )


def _evaluate(
    universe: list[CurrentStateRow], series: list[DailySeriesRow], **overrides: int
) -> list[StockoutRiskRow]:
    kwargs = {
        "window_days": WINDOW,
        "at_risk_below_days": AT_RISK,
        "stale_after_days": STALE,
        "min_observations": MIN_OBS,
    }
    kwargs.update(overrides)
    return list(evaluate_stockout_risk(universe, series, as_of=AS_OF, **kwargs))


def _fresh_series(quantity: str = "28.000", days: int = 7) -> list[DailySeriesRow]:
    """``days`` consecutive recent observations, ending yesterday so nothing is stale."""
    return [_day(offset, quantity) for offset in range(1, days + 1)]


# ---------------------------------------------------------------------------
# The arithmetic
# ---------------------------------------------------------------------------


def test_cover_is_stock_divided_by_the_mean_daily_rate_over_the_window() -> None:
    """Numbers chosen so the answer is obvious by hand: 7 days x 4 units = 28 units over a
    28-day window is exactly 1 unit/day, so 70 units of stock is 70 days of cover."""
    (row,) = _evaluate([_position(stock="70.000")], _fresh_series("4.000", days=7))
    assert row.refused_because is None
    assert row.days_of_cover == Decimal(70)
    assert not row.is_at_risk


def test_the_rate_is_over_the_whole_window_not_only_the_observed_days() -> None:
    """THE DECISION THAT IS EASY TO GET WRONG. 28 units across 7 observed days is 1/day over a
    28-day window, NOT 4/day over the days that happened to have sales.

    Dividing by observed days would treat a SKU selling once a week as if it sold every day and
    would understate cover by the ratio between them — reporting a comfortable position as
    critical. The window is the denominator because demand continues on days with no sale.
    """
    (row,) = _evaluate([_position(stock="70.000")], _fresh_series("4.000", days=7))
    assert row.days_of_cover == Decimal(70), "4/day would give 17.5"


def test_a_position_below_the_line_is_at_risk() -> None:
    """1 unit/day against 10 units of stock is 10 days of cover, inside the 14-day line."""
    (row,) = _evaluate([_position(stock="10.000")], _fresh_series("4.000", days=7))
    assert row.days_of_cover == Decimal(10)
    assert row.is_at_risk


def test_the_risk_line_is_exclusive_at_the_boundary() -> None:
    """Exactly 14 days of cover is NOT at risk. Stated because a boundary left implicit is a
    boundary that moves: 14 units at 1/day is precisely the declared horizon."""
    (row,) = _evaluate([_position(stock="14.000")], _fresh_series("4.000", days=7))
    assert row.days_of_cover == Decimal(14)
    assert not row.is_at_risk


def test_one_row_per_position_assessed_or_not() -> None:
    """The same contract as DeadStockRow. A caller can count what was CONSIDERED, so "no risk"
    and "not assessed" are distinguishable rather than both being an absence."""
    universe = [_position("SKU-1"), _position("SKU-2"), _position("SKU-3")]
    rows = _evaluate(universe, _fresh_series())
    assert len(rows) == len(universe)
    assert {row.sku_id for row in rows} == {"SKU-1", "SKU-2", "SKU-3"}


def test_observations_outside_the_window_are_ignored() -> None:
    """A sale 40 days ago is not in a 28-day window and must not raise the rate."""
    inside = _fresh_series("4.000", days=7)
    outside = [_day(40, "1000.000")]
    (row,) = _evaluate([_position(stock="70.000")], inside + outside)
    assert row.days_of_cover == Decimal(70), "the 40-day-old spike leaked into the rate"


def test_another_skus_movement_does_not_feed_this_ones_rate() -> None:
    """Grouping is per series. Mixing them would let a fast SKU mask a slow one's risk."""
    rows = _evaluate(
        [_position("SKU-1", stock="10.000"), _position("SKU-2", stock="10.000")],
        _fresh_series("4.000", days=7) + [_day(o, "400.000", "SKU-2") for o in range(1, 8)],
    )
    by_sku = {row.sku_id: row for row in rows}
    assert by_sku["SKU-1"].days_of_cover == Decimal(10)
    assert by_sku["SKU-2"].days_of_cover != Decimal(10)


# ---------------------------------------------------------------------------
# The four refusals — each is a number that would have been wrong
# ---------------------------------------------------------------------------


def test_a_null_stock_is_refused_not_treated_as_zero() -> None:
    """NULL is not zero, and canonical distinguishes them. Treating an un-stocktaken SKU as
    empty would report it as critically at risk — the most alarming possible wrong answer."""
    (row,) = _evaluate([_position(stock=None)], _fresh_series())
    assert row.days_of_cover is None
    assert not row.is_at_risk
    assert row.refused_because is not None and "NULL" in row.refused_because


def test_a_stale_series_is_refused() -> None:
    """THE ONE THAT FIRES ON TODAY'S REAL DATA. daily_series is AS_OF_DATE and current_state is
    LAST_WRITE; dividing today's stock by a rate that stopped 17 days ago mixes two instants
    separated by most of a replenishment cycle."""
    stale = [_day(offset, "4.000") for offset in range(17, 24)]
    (row,) = _evaluate([_position()], stale)
    assert row.days_of_cover is None
    assert row.refused_because is not None and "days before" in row.refused_because


def test_staleness_is_measured_per_series_not_per_tenant() -> None:
    """WHY THIS IS NOT A SECOND GATE. A gate refuses the whole tenant before any fetch; one
    stale SKU must not block the other forty-five."""
    universe = [_position("SKU-FRESH"), _position("SKU-STALE")]
    series = [
        *[_day(offset, "4.000", "SKU-FRESH") for offset in range(1, 8)],
        *[_day(offset, "4.000", "SKU-STALE") for offset in range(17, 24)],
    ]
    by_sku = {row.sku_id: row for row in _evaluate(universe, series)}
    assert by_sku["SKU-FRESH"].refused_because is None
    assert by_sku["SKU-STALE"].refused_because is not None


def test_too_few_observations_inside_the_window_is_refused() -> None:
    """THE GATE/WINDOW MISMATCH, made visible. The gate measures coverage over the tenant's
    WHOLE history; the rate uses a trailing window. A series can clear a 7-day gate on old
    history and have almost nothing in the window the arithmetic actually uses."""
    (row,) = _evaluate([_position()], _fresh_series("4.000", days=3))
    assert row.days_of_cover is None
    assert row.refused_because is not None and "fewer than" in row.refused_because


def test_a_negative_net_quantity_is_refused_not_clamped() -> None:
    """43 RETURN rows exist in staging, so this is reachable. A negative rate yields negative
    days of cover — not an approximation, a number with no meaning.

    NOT CLAMPED TO ZERO: that would publish "not at risk", a verdict about a SKU whose own data
    says something is wrong with it or with the ingestion behind it.
    """
    returns_heavy = [_day(offset, "-4.000") for offset in range(1, 8)]
    (row,) = _evaluate([_position()], returns_heavy)
    assert row.days_of_cover is None
    assert not row.is_at_risk
    assert row.refused_because is not None and "not positive" in row.refused_because


def test_a_net_quantity_of_exactly_zero_is_refused() -> None:
    """The division-by-zero case, which is the boundary of the one above rather than a separate
    idea. Sales exactly cancelled by returns."""
    cancelled = [_day(1, "4.000"), *[_day(o, "0.000") for o in range(2, 8)], _day(8, "-4.000")]
    (row,) = _evaluate([_position()], cancelled, min_observations=8)
    assert row.days_of_cover is None
    assert row.refused_because is not None and "not positive" in row.refused_because


def test_no_observations_at_all_in_the_window_is_refused() -> None:
    (row,) = _evaluate([_position()], [])
    assert row.days_of_cover is None
    assert row.refused_because is not None and "no observations" in row.refused_because


def test_staleness_is_reported_before_thinness_when_both_apply() -> None:
    """ORDER IS DELIBERATE. A series that is both stale and thin is reported as stale, because
    refreshing the data may resolve both while collecting more of a stale series resolves
    neither. The reported reason should be the one an operator can act on."""
    (row,) = _evaluate([_position()], [_day(20, "4.000"), _day(21, "4.000")])
    assert row.refused_because is not None and "days before" in row.refused_because


# ---------------------------------------------------------------------------
# The row type makes a refused-and-flagged row unconstructible
# ---------------------------------------------------------------------------


def test_a_refused_row_cannot_carry_a_cover_figure() -> None:
    with pytest.raises(ValueError, match="carries a cover figure"):
        StockoutRiskRow(
            tenant_id=TENANT,
            store_id=STORE,
            sku_id="SKU-1",
            days_of_cover=Decimal(3),
            is_at_risk=False,
            refused_because="stale",
        )


def test_a_refused_row_cannot_be_flagged_at_risk() -> None:
    """THE ONE THAT MATTERS: an action must never come from a refusal. The proposer also skips
    refused rows, but this makes the bad state unconstructible rather than merely unproduced."""
    with pytest.raises(ValueError, match="is flagged at risk"):
        StockoutRiskRow(
            tenant_id=TENANT,
            store_id=STORE,
            sku_id="SKU-1",
            days_of_cover=None,
            is_at_risk=True,
            refused_because="stale",
        )


def test_an_unassessed_row_must_say_why() -> None:
    """No cover and no reason is an invisible gap — exactly what refused_because exists to
    prevent."""
    with pytest.raises(ValueError, match="no refusal reason"):
        StockoutRiskRow(
            tenant_id=TENANT,
            store_id=STORE,
            sku_id="SKU-1",
            days_of_cover=None,
            is_at_risk=False,
            refused_because=None,
        )


# ---------------------------------------------------------------------------
# Summarising refusals, since synapse.run records counts and not reasons
# ---------------------------------------------------------------------------


def test_reasons_group_by_category_not_by_their_specifics() -> None:
    """The reasons embed dates and counts, so grouping on the whole string would give one
    bucket per row and summarise nothing."""
    universe = [_position(f"SKU-{n}") for n in range(3)]
    series = [_day(o, "4.000", f"SKU-{n}") for n in range(3) for o in range(17, 24)]
    counts = counts_by_reason(_evaluate(universe, series))
    assert len(counts) == 1, f"three stale series should be one category, got {dict(counts)}"
    assert sum(counts.values()) == 3


def test_assessed_rows_are_not_counted_as_refusals() -> None:
    assert counts_by_reason(_evaluate([_position()], _fresh_series())) == {}


def test_the_evaluator_rejects_a_nonsensical_window() -> None:
    with pytest.raises(ValueError, match="window_days must be at least 1"):
        _evaluate([_position()], _fresh_series(), window_days=0)
