"""dead_stock end to end: resolve the declaration, fetch both inputs, evaluate.

THE FIRST THING IN THIS PLATFORM THAT PRODUCES AN ANSWER. Every live test before this one
verified availability — can this be read, does this tenant have enough history, do these two
capabilities compose. This computes a result and reports a number.

  test_it_resolves_and_both_fetchers_execute   NO DATA REQUIRED -> the local stack
  test_it_evaluates_against_real_rows          DATA REQUIRED    -> staging

See conftest.py's header for the full invocation. The first test needs nothing but
`make run-local`: with two GATELESS requirements no probe runs, so Satisfied is a static fact
about the registry, and what the database is needed for is that both resolvers actually EXECUTE
in one flow — two collapses, two aggregates, one declaration.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from datetime import date
from typing import Any, assert_never
from uuid import UUID

import pytest

from synapse.core.analysis import DEAD_STOCK
from synapse.core.capability import CapabilityScope
from synapse.core.declaration_resolution import (
    DeclarationBlocked,
    DeclarationSatisfied,
    DeclarationUndeclared,
)
from synapse.core.refusal import counts_by_reason

DSN = os.environ.get("SYNAPSE_READER_URL")
TENANT = os.environ.get("SYNAPSE_TEST_TENANT_ID")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DSN or not TENANT,
        reason=(
            "needs SYNAPSE_READER_URL (a synapse_reader DSN, NOT ithina_dis_user) and "
            "SYNAPSE_TEST_TENANT_ID; the resolve test runs against the LOCAL stack"
        ),
    ),
]

RequireRows = Callable[..., Coroutine[Any, Any, int]]


def _scope() -> CapabilityScope:
    return CapabilityScope(tenant_id=UUID(str(TENANT)))


async def test_it_resolves_and_both_fetchers_execute() -> None:
    """NO DATA REQUIRED. The composition PLUMBING, executed rather than reasoned about.

    Until this existed, ``_check_declarations()`` verified at import that dead_stock's grain was
    joinable and its fields were real, and nothing had ever fetched a row for it. What this adds:

    - ``resolve_declaration`` returns Satisfied for a real registry against a real database.
    - BOTH fetchers execute — two collapses over the sale-events table and one hot-table read,
      driven by a declaration rather than by hand.
    - the evaluator runs on whatever came back.

    Zero rows is a genuine pass: two resolvers executing is the claim, and an empty tenant has no
    dead stock, which is a true answer. The NUMBERS are the staging test's job.
    """
    from dis_rls import create_rls_engine
    from synapse.core.current_state import CurrentStateRow
    from synapse.core.dead_stock import evaluate_dead_stock
    from synapse.core.last_sale_at import LastSaleAtRow
    from synapse.registry import resolve_declaration

    # BY NAME, NOT BY POSITION. A positional unpack breaks silently if a threshold field
    # is ever added or reordered: the integration suite only runs inside a staging window,
    # so unit-test call sites can be fixed the same day while these two go unnoticed until
    # the next window.
    stale_after = next(t for t in DEAD_STOCK.thresholds if t.name == "stale_after_days")
    feed_stale_after = next(t for t in DEAD_STOCK.thresholds if t.name == "feed_stale_after_days")
    engine = create_rls_engine(DSN)
    try:
        outcome = await resolve_declaration(engine, "dead_stock", _scope())
        assert isinstance(outcome, DeclarationSatisfied), f"dead_stock did not resolve: {outcome}"
        assert set(outcome.fetches) == {"current_state", "last_sale_at"}

        universe = await outcome.fetches["current_state"]()
        selling = await outcome.fetches["last_sale_at"]()
    finally:
        await engine.dispose()

    assert all(isinstance(row, CurrentStateRow) for row in universe)
    assert all(isinstance(row, LastSaleAtRow) for row in selling)

    evaluated = evaluate_dead_stock(
        universe,  # type: ignore[arg-type]
        selling,  # type: ignore[arg-type]
        stale_after_days=stale_after.days,
        feed_stale_after_days=feed_stale_after.days,
        as_of=date.today(),
    )
    # One row per position, dead or not — the evaluator's contract.
    assert len(evaluated) == len(universe)


async def test_it_evaluates_against_real_rows(require_canonical_rows: RequireRows) -> None:
    """DATA REQUIRED. The exit condition: a real, partial answer on real rows.

    Reports three numbers, because a count on its own cannot be sanity-checked:

    - how many of the universe are dead stock,
    - how many came back with ``days_since_last_sale is None`` (never sold),
    - the most recent sale date in the tenant.

    WHY THE ANSWER SHOULD BE PARTIAL, and why 66-of-66 is a stop-and-look rather than a result.
    At ``stale_after_days=90``, a position is dead only if its last sale predates roughly the
    first week of the data window. So a healthy outcome is SOME flagged and most not. If every
    position comes back dead, the likely causes are: the data is older than it looks, the
    universe and the selling set failed to join (the subset claim — see
    test_last_sale_at_live.py), or ``as_of`` is wrong. All three are worth stopping on, and none
    of them is "the catalogue is dead".
    """
    from sqlalchemy import text

    from dis_rls import create_rls_engine, rls_session
    from synapse.core.dead_stock import evaluate_dead_stock
    from synapse.registry import resolve_declaration

    stale_after = next(t for t in DEAD_STOCK.thresholds if t.name == "stale_after_days")
    feed_stale_after = next(t for t in DEAD_STOCK.thresholds if t.name == "feed_stale_after_days")
    as_of = date.today()
    scope = _scope()
    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, scope.tenant_id) as conn:
            await require_canonical_rows(
                conn,
                scope.tenant_id,
                table="current_position",
                what="it needs a universe to evaluate dead stock over",
            )
            await require_canonical_rows(
                conn,
                scope.tenant_id,
                table="sale_events",
                what="it needs sales to date positions against",
            )
            most_recent = (
                await conn.execute(
                    text(
                        "SELECT MAX(event_date) FROM canonical.store_sku_sale_events "
                        "WHERE tenant_id = CAST(:tenant AS uuid) AND event_subtype = 'SALE'"
                    ),
                    {"tenant": str(scope.tenant_id)},
                )
            ).scalar_one()

        outcome = await resolve_declaration(engine, "dead_stock", scope)
        assert isinstance(outcome, DeclarationSatisfied), f"dead_stock did not resolve: {outcome}"
        universe = await outcome.fetches["current_state"]()
        selling = await outcome.fetches["last_sale_at"]()
    finally:
        await engine.dispose()

    evaluated = evaluate_dead_stock(
        universe,  # type: ignore[arg-type]
        selling,  # type: ignore[arg-type]
        stale_after_days=stale_after.days,
        feed_stale_after_days=feed_stale_after.days,
        as_of=as_of,
    )
    dead = [row for row in evaluated if row.is_dead_stock]
    never_sold = [row for row in evaluated if row.days_since_last_sale is None]
    # THE REFUSALS ARE PRINTED TOO, and without them this report is misleading rather than merely
    # incomplete: since the analysis gained a premise check and a feed check, "3 of 66 dead" is
    # consistent with 63 assessed and with 63 refused, and those are opposite situations.
    refused = counts_by_reason(evaluated)

    print(
        f"\ndead_stock as_of {as_of}, stale_after_days={stale_after.days}, "
        f"feed_stale_after_days={feed_stale_after.days}: "
        f"{len(dead)} of {len(evaluated)} positions dead, "
        f"{len(never_sold)} never sold, "
        f"refused {dict(sorted((r.value, n) for r, n in refused.items()))}, "
        f"most recent SALE {most_recent}, "
        f"{len(selling)} of {len(universe)} positions have ever sold"
    )

    assert evaluated, "guarded above; an empty evaluation proves nothing"
    assert len(evaluated) == len(universe), "one row per position, dead or not"

    # A REAL ANSWER IS PARTIAL. All-dead is arithmetically possible and analytically suspect: see
    # the docstring for the three likely causes, none of which is a dead catalogue.
    #
    # ALL-REFUSED IS NOT THE SAME FAILURE AND IS NOT ASSERTED AGAINST. A fleet where no tenant has
    # current sales data legitimately produces zero dead and one refusal per position, which is
    # the system being honest rather than broken. The print above is what makes that readable.
    assert len(dead) < len(evaluated), (
        f"every one of {len(evaluated)} positions came back dead. Most recent SALE is "
        f"{most_recent} against as_of {as_of} and a {stale_after.days}-day threshold. Check, in "
        "order: whether the universe and the selling set joined at all (the subset claim), "
        "whether the data is older than expected, and whether as_of is right"
    )


async def test_the_three_declaration_outcomes_are_exhaustive_against_a_real_database() -> None:
    """NO DATA REQUIRED. The console's branch, run for real.

    Mirrors test_daily_series_live's equivalent one level up: whichever outcome arrives is a real
    one, and ``assert_never`` is what makes a fourth outcome a type error rather than a silent
    fall-through.
    """
    from dis_rls import create_rls_engine
    from synapse.registry import resolve_declaration

    engine = create_rls_engine(DSN)
    try:
        outcome = await resolve_declaration(engine, "dead_stock", _scope())
    finally:
        await engine.dispose()

    match outcome:
        case DeclarationSatisfied():
            assert set(outcome.fetches) == {"current_state", "last_sale_at"}
        case DeclarationBlocked():  # pragma: no cover - both requirements are registered
            pytest.fail(f"dead_stock blocked on {sorted(outcome.blocked)}")
        case DeclarationUndeclared():  # pragma: no cover - it is in _DECLARATIONS
            pytest.fail("dead_stock is declared; this outcome means the registry moved")
        case _:  # pragma: no cover
            assert_never(outcome)
