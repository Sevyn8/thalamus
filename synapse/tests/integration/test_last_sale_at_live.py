"""last_sale_at against a live canonical. TWO TESTS, TWO DIFFERENT ENVIRONMENTS.

Written because slice 2 shipped this capability with no live coverage at all: its SQL existed
only as compiled-string assertions, and dead_stock rests on it. See conftest.py's header for
the full invocation.

  test_it_executes_and_every_row_projects        NO DATA REQUIRED -> THE LOCAL STACK
  test_selling_positions_are_a_subset_of_the_universe   DATA REQUIRED -> staging

THE FIRST ONE NEEDS NOTHING BUT `make run-local`, and that is the entire reason the
no-data-required category exists. A DISTINCT ON whose expressions do not match the leading
ORDER BY is a RUNTIME ERROR Postgres raises at ZERO ROWS, so an empty local database proves
exactly the thing a compiled-string assertion cannot: that the statement is valid SQL rather
than valid-according-to-my-regex. No staging DSN, no private-IP access, no window to close.

    LOCAL='postgresql+psycopg://synapse_reader:synapse_reader_password@localhost:5433'
    SYNAPSE_READER_URL="$LOCAL/ithina_dis_db" \\
    SYNAPSE_TEST_TENANT_ID='<any tenant uuid>' \\
    uv run pytest -c pyproject.toml ../synapse/tests/integration/test_last_sale_at_live.py

(Locally `DIS_EXPECTED_DATABASE` is already the default and dis_testing's sync is correct, so
neither of the staging-only flags is needed.)

THE SECOND ONE NEEDS REAL ROWS and batches with whatever else next warrants a staging window.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from datetime import date
from typing import Any
from uuid import UUID

import pytest

from synapse.core.capability import CapabilityScope

DSN = os.environ.get("SYNAPSE_READER_URL")
TENANT = os.environ.get("SYNAPSE_TEST_TENANT_ID")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DSN or not TENANT,
        reason=(
            "needs SYNAPSE_READER_URL (a synapse_reader DSN, NOT ithina_dis_user) and "
            "SYNAPSE_TEST_TENANT_ID; the executability test runs against the LOCAL stack"
        ),
    ),
]

# Structural alias for the conftest fixture's callable. Declared rather than imported: the
# suite runs under --import-mode=importlib with no __init__.py, so a sibling import of
# conftest is fragile. The fixture itself arrives by name, which is not.
RequireRows = Callable[..., Coroutine[Any, Any, int]]


def _scope() -> CapabilityScope:
    return CapabilityScope(tenant_id=UUID(str(TENANT)))


async def test_it_executes_and_every_row_projects() -> None:
    """NO DATA REQUIRED, AND RUNS ON THE LOCAL STACK.

    An empty result is a genuine PASS, and not vacuously. What this exercises is that the
    statement EXECUTES:

    - a DISTINCT ON whose expressions do not match the leading ORDER BY is a runtime error
      Postgres raises at zero rows. The unit suite asserts the compiled string; only Postgres
      can tell "matches" from "matches according to my regex".
    - the subtype filter is applied to a collapsed subquery, and `IN` over a column the
      collapse must have projected is another shape that fails only on execution.
    - a canonical rename fails here too, also at zero rows, because the column list is derived
      from the canonical model and named in the SELECT.

    THIS CAPABILITY HAD NO LIVE COVERAGE WHEN IT SHIPPED. daily_series got this test in slice
    1; last_sale_at reuses the same collapse and builds a structurally similar aggregate on top
    of it, and nothing had ever run it.

    The per-row assertions are a bonus when rows exist. Their absence is not an error — that is
    what makes this the test that needs no data.
    """
    from dis_rls import create_rls_engine
    from synapse.resolvers.last_sale_at import resolve_last_sale_at

    engine = create_rls_engine(DSN)
    try:
        rows = await resolve_last_sale_at(engine, _scope())
    finally:
        await engine.dispose()

    for row in rows:
        assert row.tenant_id == UUID(str(TENANT)), "RLS and the tenant predicate must agree"
        # A plain date, never a datetime: the contract promises a UTC day, which is the grain
        # canonical's CHECK constraint actually guarantees.
        assert type(row.last_sale_date) is date
        assert row.sku_id, "sku_id is NOT NULL in canonical"


async def test_selling_positions_are_a_subset_of_the_universe(
    require_canonical_rows: RequireRows,
) -> None:
    """DATA REQUIRED. **THE COMPOSITION CLAIM dead_stock RESTS ON**, stated as a claim:

        EVERY SKU THAT HAS SOLD IS A SKU THAT EXISTS.

    dead_stock derives an absence by subtracting last_sale_at (the positions that have ever
    sold) from current_state (the universe of positions). That subtraction is only meaningful
    if the second set contains the first. If a selling position is missing from the universe,
    dead_stock does not error — it computes over a SMALLER UNIVERSE and reports fewer dead SKUs
    than exist. Wrong in the permissive direction, and it reads as a healthier catalogue rather
    than as a fault, which is the direction nobody investigates.

    IT IS NOT A DATABASE CONSTRAINT. Nothing enforces it: sale events carry no foreign key to
    store_sku_current_position (the DDL says so explicitly — lifecycle independence, because
    sale events outlive current_position rows for delisted SKUs, and bootstrap, because a new
    SKU's first sale may be written before its position exists). So this is a claim about the
    DATA that has to be checked against data, and the two documented reasons the FK was omitted
    are exactly the two ways it can legitimately break. If it fails, the finding is not "fix
    the constraint" — it is "dead_stock's universe needs a wider source than current_state".

    Requires BOTH tables to be non-empty: with an empty universe the subset holds trivially,
    and with no sales there is nothing to be a subset of.
    """
    from dis_rls import create_rls_engine, rls_session
    from synapse.resolvers.current_state import _MAX_ROWS as CURRENT_STATE_MAX_ROWS
    from synapse.resolvers.current_state import resolve_current_state
    from synapse.resolvers.last_sale_at import resolve_last_sale_at

    scope = _scope()
    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, scope.tenant_id) as conn:
            await require_canonical_rows(
                conn,
                scope.tenant_id,
                table="current_position",
                what="it needs a universe to check selling positions against",
            )
            await require_canonical_rows(
                conn,
                scope.tenant_id,
                table="sale_events",
                what="it needs sales to check are inside the universe",
            )
        universe = await resolve_current_state(engine, scope, limit=CURRENT_STATE_MAX_ROWS)
        selling = await resolve_last_sale_at(engine, scope)
    finally:
        await engine.dispose()

    # current_state CLAMPS rather than raising (its grain does not multiply by days, so a
    # caller can see it got exactly the limit). If it did, the universe is truncated and a
    # subset violation below would be an artefact of truncation rather than a real finding.
    # Fail with that said, rather than reporting a false positive.
    if len(universe) >= CURRENT_STATE_MAX_ROWS:
        pytest.fail(
            f"current_state returned {len(universe)} rows, at or above its clamp of "
            f"{CURRENT_STATE_MAX_ROWS}, so the universe may be truncated and this comparison "
            "cannot distinguish a real subset violation from a missing page"
        )

    universe_keys = {(row.tenant_id, row.store_id, row.sku_id) for row in universe}
    selling_keys = {(row.tenant_id, row.store_id, row.sku_id) for row in selling}

    assert selling_keys, "guarded above; an empty selling set is a subset of anything"
    orphans = sorted(selling_keys - universe_keys)
    assert not orphans, (
        f"{len(orphans)} position(s) have sold but are absent from current_state, so "
        f"dead_stock would compute over a smaller universe and under-report dead stock. "
        f"First few: {orphans[:5]}. Sale events carry no FK to the hot table by design "
        "(lifecycle independence for delisted SKUs; bootstrap before a position exists), so "
        "this is a data claim, not a constraint — dead_stock needs a wider universe source"
    )
