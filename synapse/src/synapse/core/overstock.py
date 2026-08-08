"""Overstock: capital sitting still, and how much of it.

THE OTHER TAIL OF ONE ARITHMETIC. ``days_of_cover = stock_qty / mean daily net demand`` is
exactly what ``stockout_risk`` computes; this reads the same number from the high end. That is
deliberate and it buys three things: one computation with three consumers (M1 detects, M2 finds
bundle partners, M3 prices), a mutual exclusion that is STRUCTURAL rather than a rule — cover
>= 30 and cover < 14 cannot both hold, so a markdown can never be proposed on a stockout
candidate — and the whole refusal vocabulary reused without a new member.

RETAIL VALUE, NOT COST, AND THE NAME SAYS SO. ``retail_value_locked = stock_qty x
current_retail_price``. It is NOT margin, NOT cost, and NOT "money at risk". The governing rule
is stockout_risk.py:14-17: canonical's ``tax_treatment`` is TBD, so ``unit_cost`` has no
determined basis and any figure derived from it would be a confident wrong number. ``unit_cost``
is nullable on every position today and would produce nothing anyway. When a cost snapshot
exists this becomes an upgrade, not a rewrite: a second field beside this one.

WHY NON-POSITIVE DEMAND STAYS A REFUSAL RATHER THAN BECOMING THE HEADLINE FINDING. A window
whose returns meet or exceed its sales sums to zero or below, and zero demand makes cover
UNDEFINED, not infinite. The tempting move is to call that the most overstocked position of
all; it is the wrong move. "This never sells" is ``dead_stock``'s claim, made on recency over
ninety days, and letting overstock annex it would put two analyses on one target with nothing to
adjudicate precedence. Undefined is undefined, and the honest answer is that we cannot tell.

ONE ROW PER POSITION, assessed or refused, the same contract as the other two analyses.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from uuid import UUID

from synapse.core.cover import assess_cover
from synapse.core.current_state import CurrentStateRow
from synapse.core.daily_series import DailySeriesRow
from synapse.core.refusal import RefusalReason

__all__ = ["OverstockRow", "counts_by_reason", "evaluate_overstock"]

# Money, rounded HALF_UP at the boundary rather than left to the database's cast. An implicit
# truncation on INSERT is a silent change to a stored number; doing it here makes the rounding a
# stated decision and keeps the finding and the column identical.
_MONEY = Decimal("0.01")


@dataclass(frozen=True)
class OverstockRow:
    """One position: how long its stock lasts, and what that stock is worth at retail."""

    tenant_id: UUID
    store_id: UUID
    sku_id: str
    days_of_cover: Decimal | None
    # None whenever the row was refused, or when the position carries no price. RETAIL value at
    # the detection-time price -- see the module docstring for why it is not cost.
    retail_value_locked: Decimal | None
    is_overstocked: bool
    refused_because: str | None
    refusal_reason: RefusalReason | None = None

    def __post_init__(self) -> None:
        if (self.refused_because is None) != (self.refusal_reason is None):
            raise ValueError(
                f"{self.sku_id!r} has refused_because={self.refused_because!r} and "
                f"refusal_reason={self.refusal_reason!r}. A refusal must carry BOTH the prose and "
                "its category, or a stored breakdown and the row a reader opens disagree about "
                "whether this position was assessed"
            )
        if self.refused_because is not None:
            if self.days_of_cover is not None:
                raise ValueError(
                    f"{self.sku_id!r} was refused ({self.refused_because}) but carries a cover "
                    "figure. A refusal means the number could not be computed"
                )
            if self.is_overstocked:
                raise ValueError(
                    f"{self.sku_id!r} was refused ({self.refused_because}) but is flagged as "
                    "overstocked. A refusal is not a verdict, and an action must never come from one"
                )
        elif self.days_of_cover is None:
            raise ValueError(
                f"{self.sku_id!r} has no cover figure and no refusal reason. Every unassessed "
                "row must say why, or the gap is invisible"
            )


def evaluate_overstock(
    universe: Sequence[CurrentStateRow],
    series: Sequence[DailySeriesRow],
    *,
    window_days: int,
    overstock_after_days: int,
    stale_after_days: int,
    min_observations: int,
    as_of: date,
) -> Sequence[OverstockRow]:
    """Days of cover per position, the value locked in it, or a stated reason there is neither.

    ``as_of`` IS A PARAMETER, never a clock read -- the same discipline as the other two
    evaluators, and for the same payoff: a boundary is testable without waiting for one.

    ``>= overstock_after_days``, inclusive, matching dead_stock's boundary convention.

    PURE. Rows in, rows out; no engine, no clock, no registry.
    """
    if overstock_after_days < 1:
        raise ValueError(f"overstock_after_days must be at least 1 day, got {overstock_after_days}")

    evaluated: list[OverstockRow] = []
    for position, cover, refusal in assess_cover(
        universe,
        series,
        window_days=window_days,
        stale_after_days=stale_after_days,
        min_observations=min_observations,
        as_of=as_of,
    ):
        if refusal is not None:
            reason, prose = refusal
            evaluated.append(
                OverstockRow(
                    tenant_id=position.tenant_id,
                    store_id=position.store_id,
                    sku_id=position.sku_id,
                    days_of_cover=None,
                    retail_value_locked=None,
                    is_overstocked=False,
                    refused_because=prose,
                    refusal_reason=reason,
                )
            )
            continue

        assert cover is not None  # noqa: S101 - refused above; narrowing for the type checker
        stock = position.stock_qty
        assert stock is not None  # noqa: S101 - NO_STOCK_QUANTITY refuses this first
        value = (stock * position.current_retail_price).quantize(_MONEY, rounding=ROUND_HALF_UP)
        evaluated.append(
            OverstockRow(
                tenant_id=position.tenant_id,
                store_id=position.store_id,
                sku_id=position.sku_id,
                days_of_cover=cover,
                retail_value_locked=value,
                is_overstocked=cover >= Decimal(overstock_after_days),
                refused_because=None,
                refusal_reason=None,
            )
        )
    return tuple(evaluated)


def counts_by_reason(rows: Sequence[OverstockRow]) -> Mapping[RefusalReason, int]:
    """Refusals grouped by the closed-vocabulary category, for synapse.run.refusals.

    TODO (gate 1, M1): this is the second copy of a function stockout_risk also has. Generalise
    it into core/refusal.py at M3, when three samples exist -- deferred deliberately rather than
    guessed from one.
    """
    counts: dict[RefusalReason, int] = {}
    for row in rows:
        if row.refusal_reason is None:
            continue
        counts[row.refusal_reason] = counts.get(row.refusal_reason, 0) + 1
    return counts
