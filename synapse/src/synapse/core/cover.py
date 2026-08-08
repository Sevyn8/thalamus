"""days_of_cover, computed ONCE. Read from the low end by stockout_risk, the high end by overstock.

    days_of_cover = stock_qty / mean daily net demand over a trailing window

WHY THIS MODULE EXISTS. It was inside ``stockout_risk`` while stockout_risk was the only
analysis that needed it. ``overstock_cash_locked`` is the SAME arithmetic read from the other
tail, and M3's markdown will be a third reader. Three copies of one quotient is three places for
the window arithmetic, the refusal ORDER, and the boundary convention to drift apart -- and the
drift would be invisible, because each copy would keep passing its own tests.

ONE COMPUTATION, THREE CONSUMERS is also what makes M3's guardrail STRUCTURAL rather than a
rule somebody has to remember: cover >= 30 and cover < 14 cannot both hold, so a markdown can
never be proposed on a stockout candidate. That property only holds if both thresholds are read
off the same number.

THE REFUSAL ORDER IS PART OF THE CONTRACT, not an implementation detail: most-fundamental
first, so the reported reason is the one an operator should act on. A series that is BOTH stale
and thin is reported as stale, because refreshing the data may fix the thinness too.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from datetime import date, timedelta
from decimal import Decimal
from uuid import UUID

from synapse.core.current_state import CurrentStateRow
from synapse.core.daily_series import DailySeriesRow
from synapse.core.refusal import RefusalReason

__all__ = ["assess_cover"]

_Key = tuple[UUID, UUID, str]

# (position, days_of_cover, refusal) -- exactly one of the last two is None.
Assessment = tuple[CurrentStateRow, Decimal | None, tuple[RefusalReason, str] | None]


def assess_cover(
    universe: Sequence[CurrentStateRow],
    series: Sequence[DailySeriesRow],
    *,
    window_days: int,
    stale_after_days: int,
    min_observations: int,
    as_of: date,
) -> Iterator[Assessment]:
    """Yield one assessment per position in ``universe``, in universe order.

    THE UNIVERSE IS AUTHORITATIVE. A series with no position produces nothing -- a position that
    does not exist cannot be over- or under-stocked. Deliberate, and the same rule dead_stock
    states for its own left-anti-join.

    PURE. No engine, no clock, no registry.
    """
    if window_days < 1:
        raise ValueError(f"window_days must be at least 1, got {window_days}")
    window_start = as_of - timedelta(days=window_days - 1)

    in_window: dict[_Key, list[DailySeriesRow]] = {}
    for row in series:
        if window_start <= row.event_date <= as_of:
            in_window.setdefault((row.tenant_id, row.store_id, row.sku_id), []).append(row)

    for position in universe:
        observations = in_window.get((position.tenant_id, position.store_id, position.sku_id), ())
        refused = _refusal(
            position,
            observations,
            stale_after_days=stale_after_days,
            min_observations=min_observations,
            window_days=window_days,
            as_of=as_of,
        )
        if refused is not None:
            yield position, None, refused
            continue
        # Guarded by the refusals: stock is not None, the window sum is strictly positive.
        total = sum((row.net_quantity for row in observations), Decimal(0))
        rate = total / Decimal(window_days)
        stock = position.stock_qty
        assert stock is not None  # noqa: S101 - refused above; narrowing for the type checker
        yield position, stock / rate, None


def _refusal(
    position: CurrentStateRow,
    observations: Sequence[DailySeriesRow],
    *,
    stale_after_days: int,
    min_observations: int,
    window_days: int,
    as_of: date,
) -> tuple[RefusalReason, str] | None:
    """Why this position cannot be assessed, as (category, prose), or None.

    BOTH HALVES ARE PRODUCED AT THE SAME SITE, deliberately. Deriving the category from the prose
    afterwards is what the old ``counts_by_reason`` did, and it produced unstable keys because
    the prose interpolates dates and counts. Returning the pair means the branch that KNOWS which
    refusal this is says so directly, and the two can never drift.

    ORDERED MOST-FUNDAMENTAL FIRST, so the reported reason is the one an operator should act on.
    A series that is BOTH stale and thin is reported as stale, because refreshing the data may
    resolve both while collecting more of a stale series resolves neither.
    """
    if position.stock_qty is None:
        return (
            RefusalReason.NO_STOCK_QUANTITY,
            "stock_qty is NULL: no numerator, and NULL is not zero",
        )

    if not observations:
        return (
            RefusalReason.NO_OBSERVATIONS_IN_WINDOW,
            f"no observations in the {window_days}-day window ending {as_of.isoformat()}; "
            "the series may have cleared the gate on older history",
        )

    latest = max(row.event_date for row in observations)
    staleness = (as_of - latest).days
    if staleness > stale_after_days:
        return (
            RefusalReason.SERIES_TOO_STALE,
            f"the series ends {latest.isoformat()}, {staleness} days before {as_of.isoformat()} "
            f"and past the {stale_after_days}-day limit. Dividing current stock by a rate that "
            "stopped that long ago mixes two instants",
        )

    if len(observations) < min_observations:
        return (
            RefusalReason.TOO_FEW_OBSERVATIONS,
            f"{len(observations)} observations inside the {window_days}-day window, fewer than "
            f"the {min_observations} the gate requires. The gate measures ALL history; the rate "
            "uses this window",
        )

    total = sum((row.net_quantity for row in observations), Decimal(0))
    if total <= 0:
        return (
            RefusalReason.NO_POSITIVE_DEMAND,
            f"net demand over the window is {total}, not positive — returns met or exceeded "
            "sales. A zero rate has no cover and a negative one has no meaning",
        )

    return None
