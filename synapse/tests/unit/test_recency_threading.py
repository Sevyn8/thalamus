"""days_since_last_sale, from the sale date to the stored Action. The whole chain, offline.

WHY THIS FILE EXISTS, AND WHAT IT IS NOT. It adds no behaviour. A prior change already made
dead_stock emit per-store recency and already threaded it through the proposer ("the urgency
inputs stop being discarded"); the chain was verified end to end by running the real evaluator and the
real proposer before a line of this was written. What was missing was any assertion that it STAYS
that way — every existing proposer test drives findings that carry recency and then asserts
something else (verb, arm, provenance, is_actionable), so all four could pass against a proposer
that dropped the field on the floor.

IT ALSO ENCODES A DECISION, which is the more durable half. ``days_since_last_sale`` means
recency AT THE FLAGGED STORE — the analysis's own (store, SKU) grain — and NOT tenant-wide
recency, which is a different signal. That decision is invisible in the code: both readings are
one plausible edit apart, and the tenant-wide version would look like a bug fix to anyone who saw
a NULL on a SKU the tenant demonstrably sells. ``test_a_sale_at_a_SIBLING_store_does_not_count``
is what makes that edit fail.

DELIBERATELY SELF-CONTAINED. The helpers below duplicate two small constructors that
test_dead_stock_evaluator.py also has, rather than importing them across modules. These tests
assert an exact number produced by a fixed date arithmetic; a fixture edited in another file for
another test's reasons would change what they mean while they kept passing. Two constructor calls
is a cheap price for that independence.

NO CLOCK ANYWHERE. Every date here is a literal and ``as_of`` is passed explicitly. The value
under test is slot-relative by construction, which ``test_the_same_finding_ages_with_the_slot``
pins by evaluating one unchanged sale against two different slots.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

from synapse.core.action import Action
from synapse.core.analysis import DEAD_STOCK
from synapse.core.current_state import CurrentStateRow
from synapse.core.dead_stock import DeadStockRow, evaluate_dead_stock
from synapse.core.dead_stock_actions import propose_dead_stock_actions
from synapse.core.last_sale_at import LastSaleAtRow

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
# THE SIBLING. Same tenant, different store — the whole point of the per-store grain test.
OTHER_STORE = UUID("019e5e3c-b700-7000-93c7-83fb205285ff")

AS_OF = date(2026, 8, 7)
STALE_AFTER = 90
FEED_STALE_AFTER = 3
VERSIONS = {"current_state": "0.1.0", "last_sale_at": "0.1.0"}


def _position(sku_id: str, *, store: UUID = STORE) -> CurrentStateRow:
    return CurrentStateRow(
        tenant_id=TENANT,
        store_id=store,
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


def _sold(sku_id: str, when: date, *, store: UUID = STORE) -> LastSaleAtRow:
    return LastSaleAtRow(tenant_id=TENANT, store_id=store, sku_id=sku_id, last_sale_date=when)


def _chain(
    universe: list[CurrentStateRow],
    selling: list[LastSaleAtRow],
    *,
    as_of: date = AS_OF,
) -> tuple[dict[str, DeadStockRow], dict[str, Action]]:
    """Evaluate then propose, through the REAL functions. Returns both halves keyed by SKU.

    Both halves, because several assertions below are about the two DISAGREEING in a specific way
    — the skew case keeps a negative on the finding and drops it from the action — and a helper
    that returned only actions could not express that.

    A FRESH FEED ANCHOR IS APPENDED, for the same reason as in the evaluator suite: dead_stock
    now refuses the whole sweep when the tenant's newest sale is older than feed_stale_after_days
    or when there is no sale history at all. Every test here is about RECENCY THREADING through
    to the action, so each needs a tenant whose feed is current; without the anchor they would
    silently become tests of the feed refusal instead. The anchor is a SKU that is never in the
    universe, which the evaluator suite already pins as producing no row.
    """
    findings = list(
        evaluate_dead_stock(
            universe,
            [*selling, _sold("FEED_ANCHOR", as_of)],
            stale_after_days=STALE_AFTER,
            feed_stale_after_days=FEED_STALE_AFTER,
            as_of=as_of,
        )
    )
    actions = list(
        propose_dead_stock_actions(
            findings,
            universe,
            declaration=DEAD_STOCK,
            capability_versions=VERSIONS,
            as_of=as_of,
        )
    )
    return (
        {row.sku_id: row for row in findings},
        {action.target["sku_id"]: action for action in actions},
    )


# ---------------------------------------------------------------------------
# 1. The value survives the proposer
# ---------------------------------------------------------------------------


def test_the_action_carries_the_findings_recency() -> None:
    """THE ASSERTION THAT WAS MISSING. Every other proposer test drives a finding that carries
    recency and then asserts verb, arm, provenance or actionability — so all of them would pass
    against a proposer that set days_since_last_sale=None unconditionally.

    2026-01-19 -> 2026-08-07 is 200 days, computed once here and hard-coded rather than
    recomputed from the dates: a test that derives its expectation the same way the code does
    cannot catch the code being wrong.
    """
    findings, actions = _chain([_position("SKU-2")], [_sold("SKU-2", date(2026, 1, 19))])

    assert findings["SKU-2"].days_since_last_sale == 200
    assert actions["SKU-2"].days_since_last_sale == 200, (
        "the proposer dropped the finding's recency on the way to the Action"
    )


def test_recency_reaches_the_action_for_every_dead_position_not_just_the_first() -> None:
    """A loop that assigned outside itself, or reused one finding's value, would pass a
    single-row test. Three positions with three distinct ages."""
    universe = [_position("SKU-A"), _position("SKU-B"), _position("SKU-C")]
    selling = [
        _sold("SKU-A", date(2026, 1, 19)),  # 200
        _sold("SKU-B", date(2026, 2, 8)),  # 180
        _sold("SKU-C", date(2026, 4, 9)),  # 120
    ]
    _, actions = _chain(universe, selling)

    assert [actions[sku].days_since_last_sale for sku in ("SKU-A", "SKU-B", "SKU-C")] == [200, 180, 120]


# ---------------------------------------------------------------------------
# 2. The per-store grain decision — NULL when THIS store never sold it
# ---------------------------------------------------------------------------


def test_a_position_never_sold_at_this_store_carries_no_recency() -> None:
    """NULL IS THE CORRECT ANSWER HERE, not missing data. The observation column's COMMENT reads
    "the input was unavailable", and for a position this store has never sold there is genuinely
    no per-store recency to state."""
    findings, actions = _chain([_position("SKU-0029")], [])

    assert findings["SKU-0029"].days_since_last_sale is None
    assert findings["SKU-0029"].is_dead_stock is True, "never sold is the deadest case"
    assert actions["SKU-0029"].days_since_last_sale is None


def test_a_sale_at_a_sibling_store_does_not_count() -> None:
    """THE GRAIN DECISION, PINNED. This is the 2026-08-07 SKU-0029 shape from staging: the tenant
    demonstrably sells the SKU, but not at the flagged store, so the flagged position's recency is
    NULL and that is right.

    days_since_last_sale means recency AT THE FLAGGED STORE. Tenant-wide recency is a DIFFERENT
    signal and deliberately not computed — a mixed grain would let a busy flagship store's sales
    make a dead SKU at a quiet branch look fresh, which is the exact judgement dead_stock exists
    to make. If someone widens the join to tenant grain, this test fails and the docstring says
    why it was narrow on purpose.
    """
    universe = [_position("SKU-0029")]
    # Sold SIX DAYS AGO — but at the sibling, not here.
    selling = [_sold("SKU-0029", date(2026, 8, 1), store=OTHER_STORE)]

    findings, actions = _chain(universe, selling)

    assert findings["SKU-0029"].days_since_last_sale is None, (
        "a sibling store's sale leaked into this store's recency — the grain went tenant-wide"
    )
    assert actions["SKU-0029"].days_since_last_sale is None
    assert findings["SKU-0029"].is_dead_stock is True


def test_the_same_sku_at_two_stores_gets_two_answers() -> None:
    """The positive half of the grain decision, and the one that would survive a bug that simply
    ignored `selling` entirely. One SKU, two stores, one sale: exactly one position gets a number.
    """
    universe = [_position("SKU-0029"), _position("SKU-0029", store=OTHER_STORE)]
    selling = [_sold("SKU-0029", date(2026, 1, 19), store=OTHER_STORE)]

    findings = list(
        evaluate_dead_stock(
            universe,
            [*selling, _sold("FEED_ANCHOR", AS_OF)],
            stale_after_days=STALE_AFTER,
            feed_stale_after_days=FEED_STALE_AFTER,
            as_of=AS_OF,
        )
    )
    by_store = {row.store_id: row.days_since_last_sale for row in findings}

    assert by_store[STORE] is None
    assert by_store[OTHER_STORE] == 200


# ---------------------------------------------------------------------------
# 3. Slot-relative, never wall-clock
# ---------------------------------------------------------------------------


def test_the_same_finding_ages_with_the_slot() -> None:
    """SLOT-RELATIVE, PINNED BY CONSTRUCTION. One unchanged sale date, two slots, two answers
    thirty apart — which is only possible if as_of is the anchor.

    A wall-clock implementation would return the same number for both, and would also change its
    answer tomorrow. Neither date here is today's; both are literals.
    """
    universe = [_position("SKU-2")]
    selling = [_sold("SKU-2", date(2026, 1, 19))]

    _, july = _chain(universe, selling, as_of=date(2026, 7, 8))
    _, august = _chain(universe, selling, as_of=date(2026, 8, 7))

    assert july["SKU-2"].days_since_last_sale == 170
    assert august["SKU-2"].days_since_last_sale == 200
    assert august["SKU-2"].days_since_last_sale - july["SKU-2"].days_since_last_sale == 30


def test_a_sale_on_the_slot_itself_is_zero_not_none() -> None:
    """ZERO IS A LEGAL OBSERVATION and must not collapse into the never-sold case. `0 or None`
    anywhere on this path would turn "sold today" into "never sold" — the deadest signal there
    is — and every other test here would still pass."""
    findings, actions = _chain([_position("SKU-2")], [_sold("SKU-2", AS_OF)])

    assert findings["SKU-2"].days_since_last_sale == 0
    assert findings["SKU-2"].is_dead_stock is False
    # Sold today, so not dead, so no action at all — the proposer only acts on dead findings.
    assert "SKU-2" not in actions


# ---------------------------------------------------------------------------
# 4. Clock skew: visible on the finding, dropped from the action
# ---------------------------------------------------------------------------


def test_a_sale_dated_after_the_slot_stays_negative_on_the_finding() -> None:
    """THE EVALUATOR DOES NOT CLAMP, deliberately. canonical's event_date is source-supplied and a
    clock-skewed POS can date a sale tomorrow; clamping here would hide the skew rather than
    surface it (dead_stock.py's own note). The finding is the diagnostic surface, so the negative
    survives on it."""
    findings, _ = _chain([_position("SKU-2")], [_sold("SKU-2", date(2026, 8, 10))])

    assert findings["SKU-2"].days_since_last_sale == -3
    assert findings["SKU-2"].is_dead_stock is False, "a future-dated sale is plainly not stale"


def test_a_skewed_age_never_reaches_the_action() -> None:
    """THE OTHER HALF OF THE SAME DECISION, and the branch no test covered. A STORED negative age
    reads as extremely fresh to anything ranking on it later, so the proposer drops it to None —
    which is what the column's COMMENT already means: the input was unavailable, and a skewed
    clock is exactly that.

    Action.__post_init__ refuses a negative outright, so the alternative to this drop is not a
    wrong number but a CRASHED RUN. The existing test at test_action.py's clock-skew boundary
    proves the refusal; this proves the proposer never triggers it.
    """
    # Dead by age at this store, and ALSO carrying a skewed sibling row that must not interfere.
    universe = [_position("SKU-SKEW"), _position("SKU-2")]
    selling = [_sold("SKU-SKEW", date(2026, 8, 10)), _sold("SKU-2", date(2026, 1, 19))]

    findings, actions = _chain(universe, selling)

    # The skewed one is not stale, so it proposes nothing — the drop is proven below on a
    # position that IS dead, which is the only way the branch is reachable.
    assert findings["SKU-SKEW"].days_since_last_sale == -3
    assert "SKU-SKEW" not in actions
    # The healthy sibling is unaffected by the skewed row's presence.
    assert actions["SKU-2"].days_since_last_sale == 200


def test_the_proposer_drops_a_negative_age_rather_than_crashing() -> None:
    """THE BRANCH ITSELF (dead_stock_actions.py's negative guard), reached directly.

    A negative age cannot co-occur with is_dead_stock=True through the evaluator — a future-dated
    sale is never stale — so the only way to exercise the drop is to hand the proposer the
    combination on purpose. That is not a contrived shape: is_dead_stock and the age come from
    different inputs, and a future evaluator change could produce it. If the guard is removed,
    Action.__post_init__ raises and this test fails loudly rather than storing a negative.
    """
    skewed = DeadStockRow(
        tenant_id=TENANT,
        store_id=STORE,
        sku_id="SKU-SKEW",
        days_since_last_sale=-3,
        is_dead_stock=True,
    )
    actions = list(
        propose_dead_stock_actions(
            [skewed],
            [_position("SKU-SKEW")],
            declaration=DEAD_STOCK,
            capability_versions=VERSIONS,
            as_of=AS_OF,
        )
    )

    assert len(actions) == 1
    assert actions[0].days_since_last_sale is None, "a negative age must never be stored"


# ---------------------------------------------------------------------------
# The other observation column is not in scope, and stays that way
# ---------------------------------------------------------------------------


def test_dead_stock_still_computes_no_cover() -> None:
    """days_of_cover belongs to stockout_risk. Asserted here so this slice's edits cannot quietly
    start populating it — migration 0004's comment is the contract."""
    _, actions = _chain([_position("SKU-2")], [_sold("SKU-2", date(2026, 1, 19))])

    assert actions["SKU-2"].days_of_cover is None
