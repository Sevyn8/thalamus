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


@dataclass(frozen=True)
class DeadStockRow:
    """One position, with how long since it sold and whether that makes it dead.

    Matches ``DEAD_STOCK.emits`` field-for-field, checked at registry import — so the
    declaration's promise about what it produces is verified against what the code produces,
    rather than being a parallel list that drifts.
    """

    tenant_id: UUID
    store_id: UUID
    sku_id: str
    # ``None`` MEANS NEVER SOLD, and it is a stronger signal than any number — not missing data.
    # A position absent from last_sale_at has no sale in the entire history of the tenant, which
    # is the deadest thing in the catalogue. It is also the distinguisher a consumer needs:
    # "never sold" and "sold 200 days ago" both give is_dead_stock=True and are different
    # problems, one for the buyer and one for the merchandiser.
    days_since_last_sale: int | None
    is_dead_stock: bool


def evaluate_dead_stock(
    universe: Sequence[CurrentStateRow],
    selling: Sequence[LastSaleAtRow],
    *,
    stale_after_days: int,
    as_of: date,
) -> Sequence[DeadStockRow]:
    """Left-anti-join shaped: every position in ``universe``, dated against ``selling``.

    ONE ROW PER POSITION IN THE UNIVERSE, not one row per dead position. If it emitted only the
    dead ones, ``is_dead_stock`` would be constantly True and therefore carry no information —
    a field that never varies is a field that should not exist. Emitting the whole universe with
    a flag also matches the declared grain (one row per position) and lets a consumer count the
    denominator, which is what makes "12 of 66" sayable instead of "12".

    THE UNIVERSE IS AUTHORITATIVE, AND THAT HAS A CONSEQUENCE WORTH STATING. A position present
    in ``selling`` but absent from ``universe`` is INVISIBLE here — it produces no row. That is
    deliberate (this iterates the universe; a position that does not exist cannot be dead stock)
    and it is exactly why the subset claim has its own live test: if selling positions leak
    outside the universe, this function under-reports and does not complain. The evaluator
    cannot detect a bad universe from inside; that is the test's job, and a unit test pins this
    exclusion as designed rather than accidental.

    ``>= stale_after_days``, inclusive: a SKU whose last sale was exactly the threshold number of
    days ago IS dead. The boundary is tested on both sides — an off-by-one here silently moves
    the entire answer by one day's worth of SKUs.
    """
    if stale_after_days < 1:
        raise ValueError(f"stale_after_days must be at least 1 day, got {stale_after_days}")

    last_sold: Mapping[tuple[UUID, UUID, str], date] = {
        (row.tenant_id, row.store_id, row.sku_id): row.last_sale_date for row in selling
    }

    evaluated: list[DeadStockRow] = []
    for position in universe:
        key = (position.tenant_id, position.store_id, position.sku_id)
        last_sale_date = last_sold.get(key)
        if last_sale_date is None:
            days: int | None = None
            is_dead = True
        else:
            days = (as_of - last_sale_date).days
            # A NEGATIVE value means a sale dated after as_of, which is not this function's to
            # judge: canonical's event_date is source-supplied and a clock-skewed POS can date a
            # sale tomorrow. It is plainly not stale, so it is not dead, and the negative number
            # is passed through rather than clamped — clamping would hide the skew.
            is_dead = days >= stale_after_days
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


__all__ = ["DeadStockRow", "evaluate_dead_stock"]
