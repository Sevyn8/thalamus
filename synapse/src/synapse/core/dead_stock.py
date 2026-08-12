"""The ``dead_stock`` evaluator: the first thing in Synapse that produces an ANSWER.

Every layer before this one answered a question about availability — can this capability be
read, does this tenant have enough history, do these two capabilities compose. This computes a
result: for each position, how long since it sold and whether that makes it dead.

WHY THIS IS A FUNCTION AND NOT AN ENGINE READING THE DECLARATION. The declaration is DATA and
adding an analysis must not mean editing an engine — but that is already satisfied by the shape
this project uses everywhere else. A capability's descriptor is data and its RESOLVER is a
function, bound by a registry row; nobody calls ``resolve_current_state`` a violation. An
analysis is the identical shape: declaration row plus evaluator function. Adding a second
analysis adds a row and a function, and touches no engine.

The alternative — an engine that computes from the declaration alone — would need the
declaration to express "subtract last_sale_date from as_of and compare", i.e. an expression
language. Inventing one from a single analysis is the guessing this project has refused four
times already (cost classes, caching, substitution rules, pagination). The arithmetic lives
here for the same reason SQL lives in a resolver.

WHY IT LIVES IN ``synapse.core`` RATHER THAN A NEW ``synapse.analyses`` PACKAGE. It is pure —
no database, no SQL, no canonical row shapes, nothing but the two projections it is handed —
so ``core`` is where it belongs on the merits. But the deciding reason is mechanical: the
import-linter contracts live in dis/pyproject.toml, and a new top-level package added WITHOUT a
layers line would sit outside the enforced set entirely. That is precisely the defect slice 1
found when ``synapse.registry`` arrived while three docstrings claimed every module was
covered. Put here, the evaluator inherits the strongest contract that exists — ``synapse.core``
may not import dis_canonical, dis_rls, sqlalchemy or psycopg, directly or transitively — which
is exactly the guarantee a pure evaluator should have.

``as_of`` IS A PARAMETER, NEVER A CLOCK READ. Two reasons, and the second is the real one:
a function that reads the clock cannot be tested at a boundary, and "was this SKU dead on the
1st" is a legitimate question this shape answers for free. It also makes the evaluation an
explicit statement about WHEN it was evaluated, in the same spirit as the ``freshness`` enum.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from uuid import UUID

from synapse.core.current_state import CurrentStateRow
from synapse.core.last_sale_at import LastSaleAtRow
from synapse.core.refusal import RefusalReason


@dataclass(frozen=True)
class DeadStockRow:
    """One position: dead, not dead, or REFUSED with a stated reason.

    Matches ``DEAD_STOCK.emits`` field-for-field, checked at registry import, so the
    declaration's promise about what it produces is verified against what the code produces
    rather than being a parallel list that drifts. The two refusal fields are in ``emits`` for
    that reason: adding them here without adding them there fails at import.

    THE SHAPE MIRRORS ``StockoutRiskRow`` DELIBERATELY. That analysis already established the
    pattern that a refusal is a property of the FINDING and the plan counts them, which is what
    lets a refusal reach ``synapse.run.refusals`` at all. A second shape for the same idea would
    be a second thing to keep in step with the persistence layer.
    """

    tenant_id: UUID
    store_id: UUID
    sku_id: str
    # ``None`` MEANS NEVER SOLD AT THIS POSITION, and when the tenant has other sales it is a
    # stronger signal than any number rather than missing data: the position has no sale in the
    # whole history, which is the deadest thing in the catalogue. It is also the distinguisher a
    # consumer needs: "never sold" and "sold 200 days ago" both give is_dead_stock=True and are
    # different problems, one for the buyer and one for the merchandiser.
    #
    # THAT READING HOLDS ONLY WHEN THE TENANT HAS SALES AT ALL. If nothing has ever arrived, every
    # position is absent from last_sale_at and "never sold here" is indistinguishable from "we
    # have no sales data". That case is now a refusal (NO_SALE_HISTORY) rather than a catalogue
    # of findings, which is what stops a silent feed manufacturing an alert per product.
    days_since_last_sale: int | None
    is_dead_stock: bool
    # None when the position WAS assessed. PROSE, carrying the per-position specifics for a human
    # deciding whether the gap matters.
    refused_because: str | None = None
    # None when the position WAS assessed. The same refusal as a CLOSED-VOCABULARY category,
    # which is what a stored breakdown groups on. Defaulted so every existing construction site
    # stays valid, and pinned to refused_because by the invariant below so the two can never
    # disagree about whether this position was assessed.
    refusal_reason: RefusalReason | None = None

    def __post_init__(self) -> None:
        if (self.refused_because is None) != (self.refusal_reason is None):
            raise ValueError(
                f"{self.sku_id!r} has refused_because={self.refused_because!r} and "
                f"refusal_reason={self.refusal_reason!r}. A refusal must carry BOTH the prose and "
                "its category, or a stored breakdown and the row a reader opens disagree about "
                "whether this position was assessed"
            )
        if self.refused_because is not None and self.is_dead_stock:
            raise ValueError(
                f"{self.sku_id!r} was refused ({self.refused_because}) but is flagged dead. A "
                "refusal is not a verdict, and an action must never come from one"
            )


def evaluate_dead_stock(
    universe: Sequence[CurrentStateRow],
    selling: Sequence[LastSaleAtRow],
    *,
    stale_after_days: int,
    feed_stale_after_days: int,
    as_of: date,
) -> Sequence[DeadStockRow]:
    """Left-anti-join shaped: every position in ``universe``, dated against ``selling``.

    ONE ROW PER POSITION IN THE UNIVERSE, not one row per dead position, and not one row per
    ASSESSED position either. If it emitted only the dead ones, ``is_dead_stock`` would be
    constantly True and therefore carry no information; if it dropped the refused ones, a caller
    could not count what was considered. Emitting the whole universe with a flag and a reason
    matches the declared grain and lets a consumer say "12 of 66" and "20 could not be assessed".

    THE UNIVERSE IS AUTHORITATIVE, AND THAT HAS A CONSEQUENCE WORTH STATING. A position present
    in ``selling`` but absent from ``universe`` is INVISIBLE here: it produces no row. That is
    deliberate (this iterates the universe; a position that does not exist cannot be dead stock)
    and it is exactly why the subset claim has its own live test. The evaluator cannot detect a
    bad universe from inside; that is the test's job, and a unit test pins this exclusion as
    designed rather than accidental.

    ``>= stale_after_days``, inclusive: a SKU whose last sale was exactly the threshold number of
    days ago IS dead. The boundary is tested on both sides; an off-by-one here silently moves the
    entire answer by one day's worth of SKUs.

    ``> feed_stale_after_days``, EXCLUSIVE, and the asymmetry with the line above is not a slip.
    Three places already ask "is this tenant's data too old" and all three use strictly greater:
    stockout_risk's own staleness refusal, orchestrator/freshness.py, and the fleet roster. A
    fourth convention for the same question would make two screens disagree about a tenant at
    exactly the boundary.

    THE TWO FEED REFUSALS ARE COMPUTED ONCE, NOT PER POSITION. Feed staleness is a property of
    the TENANT, so every position in the sweep carries the same verdict; deriving it inside the
    loop would be the same answer computed once per row.
    """
    if stale_after_days < 1:
        raise ValueError(f"stale_after_days must be at least 1 day, got {stale_after_days}")
    if feed_stale_after_days < 1:
        raise ValueError(f"feed_stale_after_days must be at least 1 day, got {feed_stale_after_days}")

    feed_refusal = _feed_refusal(selling, feed_stale_after_days=feed_stale_after_days, as_of=as_of)

    last_sold: Mapping[tuple[UUID, UUID, str], date] = {
        (row.tenant_id, row.store_id, row.sku_id): row.last_sale_date for row in selling
    }

    evaluated: list[DeadStockRow] = []
    for position in universe:
        refusal = feed_refusal or _stock_refusal(position)
        if refusal is not None:
            reason, prose = refusal
            evaluated.append(
                DeadStockRow(
                    tenant_id=position.tenant_id,
                    store_id=position.store_id,
                    sku_id=position.sku_id,
                    # STILL CARRIED ON A REFUSED ROW. The age is a fact about the position and is
                    # knowable whether or not the premise held, and dropping it would make a
                    # refused row less informative than it needs to be for anyone diagnosing why
                    # a catalogue went quiet.
                    days_since_last_sale=_age(last_sold, position, as_of=as_of),
                    is_dead_stock=False,
                    refused_because=prose,
                    refusal_reason=reason,
                )
            )
            continue

        days = _age(last_sold, position, as_of=as_of)
        # NO ENTRY IN last_sale_at, AND THE TENANT DOES HAVE SALES: this position has never sold
        # while others have. That is the strongest finding the analysis makes, not missing data.
        # The no-sales-at-all case never reaches here; it is refused above.
        is_dead = True if days is None else days >= stale_after_days
        evaluated.append(
            DeadStockRow(
                tenant_id=position.tenant_id,
                store_id=position.store_id,
                sku_id=position.sku_id,
                days_since_last_sale=days,
                is_dead_stock=is_dead,
            )
        )
    return evaluated


def _age(
    last_sold: Mapping[tuple[UUID, UUID, str], date],
    position: CurrentStateRow,
    *,
    as_of: date,
) -> int | None:
    """Days since this position last sold, or None if it never has.

    A NEGATIVE value means a sale dated after as_of, which is not this function's to judge:
    canonical's event_date is source-supplied and a clock-skewed POS can date a sale tomorrow. It
    is plainly not stale, so it is not dead, and the negative number is passed through rather
    than clamped. Clamping would hide the skew; the action proposer drops it instead, where the
    reason for dropping it is about what a STORED age would mean.
    """
    last_sale_date = last_sold.get((position.tenant_id, position.store_id, position.sku_id))
    return None if last_sale_date is None else (as_of - last_sale_date).days


def _feed_refusal(
    selling: Sequence[LastSaleAtRow],
    *,
    feed_stale_after_days: int,
    as_of: date,
) -> tuple[RefusalReason, str] | None:
    """Why NO position can be assessed, as (category, prose), or None. A tenant-level verdict.

    ===========================================================================================
    THIS IS WHAT STOPS A STALLED FEED MANUFACTURING A CATALOGUE OF ALERTS
    ===========================================================================================
    ``resolve_last_sale_at`` reads all of history with no date window, deliberately, so a tenant
    whose feed stops keeps its historical sale dates and every position's age simply increments.
    The failure is therefore DATED rather than gradual: about ``stale_after_days`` after the last
    sale, every product crosses the line on the same day and "nobody bought this" becomes
    indistinguishable from "nobody told us anything".

    The NO_SALE_HISTORY case is worse and arrives immediately: with no rows at all, every
    position is absent from ``selling``, every one reads as never-sold, and the whole catalogue
    is dead stock on the first sweep. That is not a hypothetical; it is what produced every
    dead-stock alert in staging as of 2026-08-12, all of them with a NULL age and none of them
    aged past the threshold.

    ORDERED MOST-FUNDAMENTAL FIRST, the same discipline stockout_risk's ``_refusal`` states: a
    tenant that has never sent anything is reported as such rather than as stale, because the two
    need different actions. "Never started" is an onboarding problem; "stopped sending" is an
    outage.

    BOTH HALVES AT THE SAME SITE. The branch that KNOWS which refusal this is returns the
    category and the prose together, so a stored key and the sentence a human reads can never
    drift. Same reason, same shape, as stockout_risk.
    """
    if not selling:
        return (
            RefusalReason.NO_SALE_HISTORY,
            f"no sale has ever arrived for this tenant as of {as_of.isoformat()}. Every position "
            "would read as never-sold, which is a statement about the feed rather than about the "
            "catalogue",
        )

    latest = max(row.last_sale_date for row in selling)
    age = (as_of - latest).days
    if age > feed_stale_after_days:
        return (
            RefusalReason.FEED_STALE,
            f"the newest sale is {latest.isoformat()}, {age} days before {as_of.isoformat()} and "
            f"past the {feed_stale_after_days}-day limit. Every position ages by one day per day "
            "the feed stays down, so a dead-stock verdict here measures the outage",
        )

    return None


def _stock_refusal(position: CurrentStateRow) -> tuple[RefusalReason, str] | None:
    """Why THIS position cannot be assessed, as (category, prose), or None.

    ===========================================================================================
    THE DECLARATION'S OWN PREMISE, IMPLEMENTED. "dead stock with no stock is not a problem to
    solve" was stated in DEAD_STOCK's requires comment and honoured by nothing.
    ===========================================================================================
    ZERO IS REFUSED ALONGSIDE NULL, AND THAT IS A RULING RATHER THAN AN OVERSIGHT. The next
    reader will assume zero was missed, so: NULL means no figure arrived and zero means a figure
    arrived saying none on hand. They differ in PROVENANCE and are identical in what an operator
    can do about them, which is nothing. There is no stock to review, mark down, move or write
    off in either case, and the declaration's justification covers both without distinction.

    THEY STAY TWO SEPARATE REASONS ANYWAY. The stored breakdown is what an operator reads when a
    catalogue goes quiet, and "no figure arrived for 20 products" sends them to the ingestion
    pipeline while "20 products have none on hand" does not. Merging the keys would destroy that
    distinction for ever, since nothing migrates a JSONB key.

    NEGATIVES ARE REFUSED WITH ZERO. A negative stock figure is a real value in that column and
    is not stock on hand under any reading.
    """
    if position.stock_qty is None:
        return (
            RefusalReason.NO_STOCK_QUANTITY,
            "stock_qty is NULL: no figure arrived, so the premise (stock on hand that is not "
            "selling) cannot be satisfied. NULL is not zero",
        )
    if position.stock_qty <= 0:
        return (
            RefusalReason.NO_STOCK_ON_HAND,
            f"stock_qty is {position.stock_qty}: a figure arrived and it says there is nothing on "
            "hand. Dead stock with no stock is not a problem to solve",
        )
    return None


__all__ = ["DeadStockRow", "evaluate_dead_stock"]
