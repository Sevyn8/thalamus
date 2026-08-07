"""Stockout risk: how many days of stock remain at the recent rate of sale.

THE SECOND ANALYSIS, AND THE FIRST THAT BINDS A GATE. Every abstraction in slices 1-6 was
extracted from ``dead_stock`` alone; this exists to find what breaks under a second example.

WHY THIS AND NOT OVERSTOCK. Overstock is dead_stock's claim at a different severity — both say
"stock that is not moving" — so both would propose REVIEW on overlapping targets, and nothing in
the action contract adjudicates precedence. Stockout risk is the COMPLEMENT: a SKU cannot be
simultaneously dead and about to run out, so the two analyses partition the catalogue and the
action log stays interpretable without inventing a precedence rule from its first collision.

    days_of_cover = stock_qty / mean daily net demand over a trailing window

QUANTITY ONLY. No margin, no revenue, no value at risk — canonical's ``tax_treatment`` is TBD,
so ``unit_cost`` has no determined basis and any money figure derived from it would be a
confident wrong number. ``quantity_at_stake`` on the resulting action is UNITS, as dead_stock
already does.

WHY THE EVALUATOR REFUSES RATHER THAN COMPUTES, in four cases. Every refusal is per SUBJECT and
travels as ``refused_because`` on the emitted row — declared in the analysis's ``emits`` and
checked against this dataclass at registry import. It is deliberately not a log line: a caller
reading the findings can see which series were not assessed and why, and a proposer can skip
them without knowing the reasons.

  1. ``stock_qty`` IS NULL. Cover is stock divided by a rate; with no stock figure there is no
     numerator. NULL is not zero — canonical distinguishes them, and treating an unknown as
     empty would report every un-stocktaken SKU as critically at risk.

  2. THE SERIES IS STALE. This is the one that matters most today, and it exists because the two
     capabilities describe DIFFERENT INSTANTS: ``daily_series`` is AS_OF_DATE and
     ``current_state`` is LAST_WRITE. Dividing today's stock by a rate that stops seventeen days
     ago is arithmetic across two instants separated by most of a replenishment cycle, and
     "3.2 days of cover" computed that way is confidently wrong rather than approximately right.
     The freshness enum has named this mismatch since slice 1; this is the first analysis where
     it bites.

     PER SERIES, NOT PER TENANT, AND THAT IS WHY IT IS NOT A GATE. A gate answers "can this
     analysis run for this tenant" before any fetch, and one stale SKU must not block the other
     forty-five. Staleness is a property of each series' own last observation.

  3. TOO FEW OBSERVATIONS IN THE WINDOW. The gate measures coverage over the tenant's WHOLE
     history — deliberately, since asking for a short window does not make long history
     unnecessary — while the rate is computed over a trailing window. So a series can clear a
     seven-day gate on all-time coverage and still have almost nothing inside the window the
     arithmetic actually uses. The two checks have different jobs: the gate is a cheap,
     fetch-free, tenant-level pre-check, and this is per-series correctness against the data in
     hand. Under ANY_SERIES both are needed.

  4. NON-POSITIVE DEMAND. ``net_quantity`` is net of returns, and a window whose returns exceed
     its sales sums to zero or below. A zero rate divides by zero; a negative rate yields
     negative days of cover, which is not an approximation but a number with no meaning.

     NOT CLAMPED TO ZERO, and the distinction is the point. Clamping would publish "not at
     risk", a verdict about a SKU whose own data says something is wrong with it or with the
     ingestion behind it — and canonical's sale-event CHECK constraints are already known to
     refuse a coherent RETURN row, so those rows deserve suspicion rather than arithmetic.
     "We cannot tell" is the true statement.

     The alternative is a GROSS units figure, which ``daily_series`` cannot supply: its three
     count columns are LINE counts, not units. Getting one means widening the capability's
     ``returns``, which is a canonical-schema question and not this slice's.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from synapse.core.current_state import CurrentStateRow
from synapse.core.daily_series import DailySeriesRow

__all__ = ["RefusalReason", "StockoutRiskRow", "counts_by_reason", "evaluate_stockout_risk"]

_Key = tuple[UUID, UUID, str]


class RefusalReason(StrEnum):
    """The CLOSED set of reasons a position cannot be assessed. One member per refusal branch.

    WHY A VOCABULARY NOW, WHEN THE PROSE WAS ENOUGH BEFORE. The prose was enough while the only
    consumer was a human reading a log line. It stops being enough the moment a COUNT of refusals
    is stored on ``synapse.run``, because a stored breakdown needs keys that are stable across
    runs, and these reasons are not: four of the five interpolate ``as_of``, an observation count
    or a date into their leading clause. ``counts_by_reason`` used to derive its buckets by
    splitting that prose at the first colon or semicolon, which meant a re-run of the SAME SLOT
    could produce different keys — the exact thing the run row must not do.

    DERIVED FROM THE BRANCHES, NOT INVENTED. Each member below is one arm of ``_refusal`` and
    there are no others; the pairing is asserted in the unit suite so a new branch cannot ship
    without a member.

    THE PROSE SURVIVES ALONGSIDE IT. ``refused_because`` still carries the per-series specifics —
    which date, how many observations, how stale — because that is what makes a refusal
    actionable for whoever reads one row. The enum is the groupable category; the prose is the
    evidence. Neither replaces the other.

    StrEnum so a member serialises to its own value as a JSON object key without a custom
    encoder, and so a stored breakdown reads as ``{"series_too_stale": 12}`` rather than as
    integers nobody can interpret without this file.
    """

    NO_STOCK_QUANTITY = "no_stock_quantity"
    NO_OBSERVATIONS_IN_WINDOW = "no_observations_in_window"
    SERIES_TOO_STALE = "series_too_stale"
    TOO_FEW_OBSERVATIONS = "too_few_observations"
    NO_POSITIVE_DEMAND = "no_positive_demand"


@dataclass(frozen=True)
class StockoutRiskRow:
    """One position, assessed or refused. The analysis's ``emits``, checked at registry import.

    ONE ROW PER POSITION IN THE UNIVERSE, assessed or not — the same contract as
    ``DeadStockRow``. A caller can count what was considered, not merely what was flagged, and
    the difference between "no risk" and "not assessed" is visible rather than inferred from an
    absence.
    """

    tenant_id: UUID
    store_id: UUID
    sku_id: str
    # None whenever the row was refused. Never negative and never infinite: the refusals above
    # remove exactly the inputs that would produce either.
    days_of_cover: Decimal | None
    is_at_risk: bool
    # None when the row WAS assessed. PROSE, carrying the per-series specifics — which date, how
    # stale, how many observations — for a human deciding whether the gap matters.
    refused_because: str | None
    # None when the row WAS assessed. The same refusal as a CLOSED-VOCABULARY category, which is
    # what a stored breakdown groups on; the prose above is what a reader acts on. Defaulted so
    # the field is additive for every existing construction site, and pinned to refused_because
    # by the invariant below so the two can never disagree about whether this row was refused.
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
            if self.is_at_risk:
                raise ValueError(
                    f"{self.sku_id!r} was refused ({self.refused_because}) but is flagged at "
                    "risk. A refusal is not a verdict, and an action must never come from one"
                )
        elif self.days_of_cover is None:
            raise ValueError(
                f"{self.sku_id!r} has no cover figure and no refusal reason. Every unassessed "
                "row must say why, or the gap is invisible"
            )


def evaluate_stockout_risk(
    universe: Sequence[CurrentStateRow],
    series: Sequence[DailySeriesRow],
    *,
    window_days: int,
    at_risk_below_days: int,
    stale_after_days: int,
    min_observations: int,
    as_of: date,
) -> Sequence[StockoutRiskRow]:
    """Days of cover per position, or a stated reason there is none.

    ``as_of`` IS A PARAMETER, never a clock read — same discipline as the dead_stock evaluator
    and for the same payoff: "what would we have said on the 1st" is answerable, and a boundary
    is testable without waiting for one.

    ``min_observations`` is the GATE's threshold, passed in so the in-window check uses the same
    number the gate used rather than a second constant that could drift from it.

    PURE. No engine, no clock, no registry: rows in, rows out. ``synapse.core`` is DB-free by
    contract and this is arithmetic over rows somebody else fetched.
    """
    if window_days < 1:
        raise ValueError(f"window_days must be at least 1, got {window_days}")
    window_start = as_of - timedelta(days=window_days - 1)

    in_window: dict[_Key, list[DailySeriesRow]] = {}
    for row in series:
        if window_start <= row.event_date <= as_of:
            in_window.setdefault((row.tenant_id, row.store_id, row.sku_id), []).append(row)

    return tuple(
        _assess(
            position,
            in_window.get((position.tenant_id, position.store_id, position.sku_id), ()),
            window_days=window_days,
            at_risk_below_days=at_risk_below_days,
            stale_after_days=stale_after_days,
            min_observations=min_observations,
            as_of=as_of,
        )
        for position in universe
    )


def _assess(
    position: CurrentStateRow,
    observations: Sequence[DailySeriesRow],
    *,
    window_days: int,
    at_risk_below_days: int,
    stale_after_days: int,
    min_observations: int,
    as_of: date,
) -> StockoutRiskRow:
    """One position. The refusal ORDER is deliberate — see below."""
    refused = _refusal(
        position,
        observations,
        stale_after_days=stale_after_days,
        min_observations=min_observations,
        window_days=window_days,
        as_of=as_of,
    )
    if refused is not None:
        reason, prose = refused
        return StockoutRiskRow(
            tenant_id=position.tenant_id,
            store_id=position.store_id,
            sku_id=position.sku_id,
            days_of_cover=None,
            is_at_risk=False,
            refused_because=prose,
            refusal_reason=reason,
        )

    # Guarded by the refusals: stock is not None, the window sum is strictly positive.
    total = sum((row.net_quantity for row in observations), Decimal(0))
    rate = total / Decimal(window_days)
    stock = position.stock_qty
    assert stock is not None  # noqa: S101 - refused above; narrowing for the type checker
    cover = stock / rate

    return StockoutRiskRow(
        tenant_id=position.tenant_id,
        store_id=position.store_id,
        sku_id=position.sku_id,
        days_of_cover=cover,
        is_at_risk=cover < Decimal(at_risk_below_days),
        refused_because=None,
        refusal_reason=None,
    )


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


def counts_by_reason(rows: Sequence[StockoutRiskRow]) -> Mapping[RefusalReason, int]:
    """How many positions were refused, grouped by the closed-vocabulary category.

    IT USED TO SPLIT THE PROSE, and that was the bug this slice found rather than a style
    quibble. The old implementation derived a bucket with
    ``refused_because.split(";")[0].split(":")[0]``, and four of the five reasons interpolate
    ``as_of``, an observation count or a series end-date BEFORE that split point — so the keys
    varied per position and per slot. Harmless while the output only reached a log line;
    disqualifying the moment it became a value stored on ``synapse.run``, where a re-run of the
    same slot must produce the same bytes.

    Now grouped on ``refusal_reason``, whose members are fixed. Only refused rows are counted, so
    an all-assessed run yields ``{}`` rather than a map of zeros — the absence of a key means
    nothing was refused for that reason, which is exactly what "no refusals" should serialise to.

    UNSORTED HERE BY DESIGN. The caller that persists this is responsible for ordering, because
    stability of the STORED form is a persistence concern; see ``run_postgres._COMPLETE``.
    """
    counts: dict[RefusalReason, int] = {}
    for row in rows:
        if row.refusal_reason is None:
            continue
        counts[row.refusal_reason] = counts.get(row.refusal_reason, 0) + 1
    return counts
