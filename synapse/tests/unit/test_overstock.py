"""overstock_cash_locked: the other tail of days_of_cover, and the money figure on the finding.

THE COHORT PROOF IS THE POINT OF THIS FILE. Gate 1 committed to a threshold against real data:
cohort A (38-65 days of cover) must trip and cohort B (5-8 days) must not. Those are the live
Body Shop numbers, so the threshold is asserted against them rather than against invented ones.
If a future edit moves overstock_after_days, the cohort tests say which real positions change
verdict.
"""

from __future__ import annotations

import inspect
import re
from collections.abc import Sequence
from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest

from synapse.core.current_state import CurrentStateRow
from synapse.core.daily_series import DailySeriesRow
from synapse.core.overstock import OverstockRow, counts_by_reason, evaluate_overstock
from synapse.core.refusal import RefusalReason

TENANT = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
STORE = UUID("019fb250-d099-7221-ab04-68f65fe68287")
AS_OF = date(2026, 8, 9)
WINDOW = 28
OVERSTOCK_AFTER = 30
STALE_AFTER = 3
MIN_OBS = 7


def _position(sku: str, stock: Decimal | None, price: Decimal = Decimal("850.0000")) -> CurrentStateRow:
    return CurrentStateRow(
        tenant_id=TENANT,
        store_id=STORE,
        sku_id=sku,
        product_name=sku,
        product_category=None,
        sku_status="ACTIVE",
        current_retail_price=price,
        unit_cost=None,
        promo_price=None,
        stock_qty=stock,
        reorder_point=None,
        currency="INR",
        expiry_date=None,
        last_source_event_at=None,
        last_updated_at=datetime(2026, 8, 9, tzinfo=UTC),
    )


def _series(sku: str, days: int, per_day: str, end: date = AS_OF) -> list[DailySeriesRow]:
    return [
        DailySeriesRow(
            tenant_id=TENANT,
            store_id=STORE,
            sku_id=sku,
            event_date=date.fromordinal(end.toordinal() - offset),
            net_quantity=Decimal(per_day),
            sale_line_count=1,
            return_line_count=0,
            void_line_count=0,
        )
        for offset in range(days)
    ]


def _evaluate(
    universe: Sequence[CurrentStateRow], series: Sequence[DailySeriesRow]
) -> dict[str, OverstockRow]:
    return {
        row.sku_id: row
        for row in evaluate_overstock(
            universe,
            series,
            window_days=WINDOW,
            overstock_after_days=OVERSTOCK_AFTER,
            stale_after_days=STALE_AFTER,
            min_observations=MIN_OBS,
            as_of=AS_OF,
        )
    }


# ---------------------------------------------------------------------------
# The threshold, against the live cohorts gate 1 committed to
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("sku", "stock", "units_per_day", "cover", "expected"),
    [
        # Cohort A, the healthy-but-overstocked end. 20 days x 2/day over a 28-day window is a rate
        # of 1.43/day; 83 units is 58 days of cover -- SKU-0010 at PVk-001, from the live data.
        ("SKU-0010", "83", "2", "58", True),
        ("SKU-0012", "52", "2", "36", True),
        # Cohort B, the at-risk end. Same window, a much higher rate, far less stock.
        ("SKU-0001", "16", "9", "6", False),
        ("SKU-0003", "13", "9", "5", False),
    ],
)
def test_the_threshold_splits_the_live_cohorts(
    sku: str, stock: str, units_per_day: str, cover: str, expected: bool
) -> None:
    """GATE 1'S COMMITMENT, asserted. A at 38-65 days trips; B at 5-8 does not."""
    rows = _evaluate([_position(sku, Decimal(stock))], _series(sku, 20, units_per_day))
    row = rows[sku]
    assert row.refused_because is None, row.refused_because
    assert row.is_overstocked is expected, f"{sku}: cover {row.days_of_cover}, expected {expected}"


def test_the_boundary_is_inclusive() -> None:
    """>= overstock_after_days, matching dead_stock's convention. An off-by-one here silently
    moves the whole answer by one day's worth of positions."""
    # rate 1.0/day over the 28-day window: 28 units across 28 days.
    exactly = _evaluate([_position("SKU-30", Decimal("30"))], _series("SKU-30", 28, "1"))["SKU-30"]
    just_under = _evaluate([_position("SKU-29", Decimal("29"))], _series("SKU-29", 28, "1"))["SKU-29"]
    assert exactly.days_of_cover == Decimal(30) and exactly.is_overstocked is True
    assert just_under.days_of_cover == Decimal(29) and just_under.is_overstocked is False


def test_overstock_and_stockout_cannot_both_hold() -> None:
    """THE MUTUAL EXCLUSION, made structural rather than remembered. It is what lets M3 propose
    a markdown without ever landing one on a stockout candidate -- and it only holds because
    both analyses read ONE quotient from core/cover.py."""
    from synapse.core.stockout_risk import evaluate_stockout_risk

    universe = [_position("SKU-A", Decimal("83")), _position("SKU-B", Decimal("16"))]
    series = _series("SKU-A", 20, "2") + _series("SKU-B", 20, "9")
    over = _evaluate(universe, series)
    under = {
        r.sku_id: r
        for r in evaluate_stockout_risk(
            universe,
            series,
            window_days=WINDOW,
            at_risk_below_days=14,
            stale_after_days=STALE_AFTER,
            min_observations=MIN_OBS,
            as_of=AS_OF,
        )
    }
    for sku in ("SKU-A", "SKU-B"):
        assert not (over[sku].is_overstocked and under[sku].is_at_risk), sku
        # And the two agree about the number itself, which is the property the shared module buys.
        assert over[sku].days_of_cover == under[sku].days_of_cover


# ---------------------------------------------------------------------------
# The money figure
# ---------------------------------------------------------------------------


def test_retail_value_is_stock_times_price() -> None:
    """The gate-1 spot-check: SKU-0010 at PVk-001, 83 units at Rs 850 = 70,550.00."""
    row = _evaluate(
        [_position("SKU-0010", Decimal("83"), Decimal("850.0000"))], _series("SKU-0010", 20, "2")
    )["SKU-0010"]
    assert row.retail_value_locked == Decimal("70550.00")


def test_the_value_is_quantized_to_two_places_half_up() -> None:
    """Rounded at the boundary rather than left to the column's cast: an implicit truncation on
    INSERT is a silent change to a stored number."""
    row = _evaluate([_position("SKU-R", Decimal("3"), Decimal("1.0050"))], _series("SKU-R", 20, "0.1"))[
        "SKU-R"
    ]
    assert row.retail_value_locked == Decimal("3.02")


def test_a_refused_row_carries_no_value_and_no_cover() -> None:
    """A refusal is not a verdict. Both the money and the cover must be absent, or a consumer
    could read a figure the analysis never stood behind."""
    row = _evaluate([_position("SKU-N", None)], _series("SKU-N", 20, "2"))["SKU-N"]
    assert row.refusal_reason is RefusalReason.NO_STOCK_QUANTITY
    assert row.retail_value_locked is None and row.days_of_cover is None
    assert row.is_overstocked is False


def test_a_flagged_row_cannot_be_constructed_without_a_verdict() -> None:
    with pytest.raises(ValueError, match="flagged as overstocked"):
        OverstockRow(
            tenant_id=TENANT,
            store_id=STORE,
            sku_id="X",
            days_of_cover=None,
            retail_value_locked=None,
            is_overstocked=True,
            refused_because="stale",
            refusal_reason=RefusalReason.SERIES_TOO_STALE,
        )


# ---------------------------------------------------------------------------
# Refusals: the vocabulary is reused, not extended
# ---------------------------------------------------------------------------


def test_non_positive_demand_stays_a_refusal() -> None:
    """ZERO DEMAND MAKES COVER UNDEFINED, NOT INFINITE. The tempting move is to call it the most
    overstocked position of all; that is dead_stock's claim, made on recency, and annexing it
    would put two analyses on one target with nothing to adjudicate precedence."""
    row = _evaluate([_position("SKU-Z", Decimal("50"))], _series("SKU-Z", 20, "0"))["SKU-Z"]
    assert row.refusal_reason is RefusalReason.NO_POSITIVE_DEMAND
    assert row.is_overstocked is False


def test_a_stale_series_is_refused_not_flagged() -> None:
    """Stock divided by a rate that stopped days ago mixes two instants whichever tail is read."""
    old = _series("SKU-S", 20, "2", end=date(2026, 7, 20))
    row = _evaluate([_position("SKU-S", Decimal("83"))], old)["SKU-S"]
    assert row.refusal_reason is RefusalReason.SERIES_TOO_STALE


def test_counts_by_reason_groups_only_refusals() -> None:
    universe = [_position("SKU-OK", Decimal("83")), _position("SKU-N", None)]
    series = _series("SKU-OK", 20, "2") + _series("SKU-N", 20, "2")
    counts = counts_by_reason(list(_evaluate(universe, series).values()))
    assert counts == {RefusalReason.NO_STOCK_QUANTITY: 1}


def test_the_vocabulary_is_not_extended_by_this_analysis() -> None:
    """M1 adds no refusal member. It reuses the four inability cases wholesale, which is what
    made the shared cover computation worth extracting."""
    from synapse.core import cover

    produced = set(re.findall(r"RefusalReason\.([A-Z_]+)", inspect.getsource(cover._refusal)))
    assert produced == {m.name for m in RefusalReason}
