"""stockout_risk against a real database: the gate splitting, and the narrowing it forces.

WHAT ONLY STAGING CAN SHOW. The unit suite proves the types refuse the wrong things and the
arithmetic is right on invented rows. It cannot show that a real gate SPLITS a real population —
that 7 days passes 46 of 65 rather than all or none — and a precondition that has never both
passed and refused against real data has only been half exercised.

  test_the_gate_splits_the_population        DATA REQUIRED -> staging
  test_the_fetch_is_narrowed_to_qualifiers   DATA REQUIRED -> staging
  test_dead_stock_is_not_narrowed            NO DATA       -> the local stack

THE THIRD ONE IS THE REGRESSION TEST AND IT NEEDS NO DATA. dead_stock measures no population, so
it must be narrowed to NOTHING — meaning no narrowing at all. If ``None`` and ``()`` were ever
conflated its fetches would return zero rows while still reporting Satisfied, and the analysis
would silently produce nothing for ever. That runs locally, so it cannot wait for a window.

EXPECT ZERO ACTIONS FROM THE EVALUATION TEST. Every series in staging ends 2026-07-19, so every
position is refused as stale against a 3-day limit. That is the freshness guard working, the
same way "0 of 65 have 60 days" was the correct answer — not a reason to loosen it.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from datetime import date
from typing import Any
from uuid import UUID

import pytest

from synapse.core.analysis import STOCKOUT_RISK
from synapse.core.capability import CapabilityScope
from synapse.core.declaration_resolution import DeclarationSatisfied

DSN = os.environ.get("SYNAPSE_READER_URL")
TENANT = os.environ.get("SYNAPSE_TEST_TENANT_ID")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DSN or not TENANT,
        reason="needs SYNAPSE_READER_URL (a synapse_reader DSN) and SYNAPSE_TEST_TENANT_ID",
    ),
]

RequireRows = Callable[..., Coroutine[Any, Any, int]]

# The gate's declared threshold, read off the declaration rather than restated, so this file
# cannot disagree with the analysis about what is being measured.
GATE_DAYS = next(
    gate.days
    for requirement in STOCKOUT_RISK.requires
    for gate in requirement.gates
    if requirement.capability_id == "daily_series"
)


def _scope() -> CapabilityScope:
    return CapabilityScope(tenant_id=UUID(str(TENANT)))


async def test_dead_stock_is_not_narrowed(require_canonical_rows: RequireRows) -> None:
    """NO DATA REQUIRED. THE REGRESSION THE WHOLE FIX RISKS INTRODUCING.

    Both of dead_stock's requirements are gateless, so no population is measured and both
    resolutions must carry ``qualifying is None``. Anything else — most dangerously an empty
    tuple — narrows its fetches to nothing while still reporting Satisfied, which is an analysis
    that produces zero findings for ever and reports success every night.

    Asserts on the RESOLUTIONS rather than on row counts precisely so it needs no data and runs
    on the local stack, where a window-gated test would be skipped.
    """
    from dis_rls import create_rls_engine
    from synapse.registry import resolve_declaration

    engine = create_rls_engine(DSN)
    try:
        outcome = await resolve_declaration(engine, "dead_stock", _scope())
    finally:
        await engine.dispose()

    assert isinstance(outcome, DeclarationSatisfied), f"dead_stock did not resolve: {outcome}"
    for capability_id, resolution in outcome.resolutions.items():
        assert resolution.qualifying is None, (
            f"{capability_id} was narrowed to {resolution.qualifying!r}; a gateless capability "
            "measures no population, and narrowing one to an empty set returns no rows silently"
        )


async def test_dead_stock_still_returns_its_whole_universe(
    require_canonical_rows: RequireRows,
) -> None:
    """DATA REQUIRED. The other half of the same regression, measured in rows.

    The test above proves the narrowing is absent; this proves the consequence — dead_stock's
    universe is still every position the tenant has. A narrowing bug would show here as a
    shortfall rather than as an error.
    """
    from dis_rls import create_rls_engine, rls_session
    from synapse.registry import resolve_declaration

    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, _scope().tenant_id) as conn:
            positions = await require_canonical_rows(
                conn,
                _scope().tenant_id,
                table="current_position",
                what="it compares the fetched universe against the table",
            )

        outcome = await resolve_declaration(engine, "dead_stock", _scope())
        assert isinstance(outcome, DeclarationSatisfied)
        universe = await outcome.fetches["current_state"]()
    finally:
        await engine.dispose()

    assert len(universe) == positions, (
        f"dead_stock fetched {len(universe)} of {positions} positions. A gateless capability "
        "must not be narrowed at all"
    )


async def test_the_gate_splits_the_population(require_canonical_rows: RequireRows) -> None:
    """DATA REQUIRED. THE FIRST GATE ANY ANALYSIS HAS BOUND, exercised in BOTH directions.

    A threshold that refuses everything or passes everything exercises one branch of the
    precondition path. Seven days was chosen off the measured ladder precisely because it
    splits: some series qualify and some do not, so ANY_SERIES is satisfied AND the narrowing
    has something to exclude.

    If this ever stops splitting it is a finding about the data, not a reason to move the
    threshold — so the assertion names both directions rather than a specific count, which would
    go stale the moment another sale lands.
    """
    from dis_rls import create_rls_engine, rls_session
    from synapse.resolvers.daily_series import probe_min_history_days

    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, _scope().tenant_id) as conn:
            await require_canonical_rows(
                conn,
                _scope().tenant_id,
                table="sale_events",
                what="a gate over no observations measures nothing",
            )
        observation = await probe_min_history_days(engine, _scope(), required=GATE_DAYS)
    finally:
        await engine.dispose()

    print(
        f"\ngate at {GATE_DAYS} days: {observation.pairs_qualifying} of "
        f"{observation.pairs_measured} series qualify"
    )
    assert observation.pairs_qualifying > 0, (
        f"no series clears {GATE_DAYS} days, so ANY_SERIES gives PreconditionUnmet and the "
        "analysis never runs — the gate is exercised in one direction only"
    )
    assert observation.pairs_qualifying < observation.pairs_measured, (
        f"all {observation.pairs_measured} series clear {GATE_DAYS} days, so the narrowing has "
        "nothing to exclude and the qualifying-population fix is untested against real data"
    )
    assert observation.qualifying is not None
    assert len(observation.qualifying) == observation.pairs_qualifying


async def test_the_fetch_is_narrowed_to_exactly_the_qualifying_series(
    require_canonical_rows: RequireRows,
) -> None:
    """DATA REQUIRED. THE DEFERRAL, DISCHARGED AND OBSERVED.

    The fetch must not return every series in scope, including the ones the gate had just
    refused. The rows must cover exactly the qualifying set — no more, and nothing outside it.
    """
    from dis_rls import create_rls_engine, rls_session
    from synapse.registry import resolve_declaration

    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, _scope().tenant_id) as conn:
            await require_canonical_rows(
                conn,
                _scope().tenant_id,
                table="sale_events",
                what="an empty series set cannot show a narrowing",
            )
        outcome = await resolve_declaration(engine, "stockout_risk", _scope(), as_of=date.today())
        assert isinstance(outcome, DeclarationSatisfied), f"did not resolve: {outcome}"
        qualifying = outcome.resolutions["daily_series"].qualifying
        rows = await outcome.fetches["daily_series"]()
    finally:
        await engine.dispose()

    assert qualifying is not None, "a gated capability must carry its qualifying population"
    fetched: set[tuple[str, ...]] = {
        (str(row.tenant_id), str(row.store_id), row.sku_id)  # type: ignore[attr-defined]
        for row in rows
    }
    outside = sorted(fetched - {tuple(key) for key in qualifying})
    assert not outside, (
        f"{len(outside)} series were fetched that did not clear the gate, e.g. {outside[:3]}. "
        "The verdict and the answer describe different populations"
    )


async def test_it_evaluates_and_refuses_every_stale_series(
    require_canonical_rows: RequireRows,
) -> None:
    """DATA REQUIRED. THE EXPECTED ANSWER IS ZERO ACTIONS, and that is the point.

    Staging's latest sale is 2026-07-19. Against a 3-day freshness limit every series is stale,
    so every position is refused and nothing is proposed. A run that produced actions here would
    mean the freshness guard is not firing — which matters more than a demo that shows numbers.

    Reports the refusal breakdown, because "zero actions" and "nothing was assessed" are the two
    things synapse.run cannot currently distinguish.
    """
    from dis_rls import create_rls_engine, rls_session
    from synapse.core.stockout_risk import counts_by_reason
    from synapse.registry import plan_for, resolve_declaration

    as_of = date.today()
    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, _scope().tenant_id) as conn:
            await require_canonical_rows(
                conn,
                _scope().tenant_id,
                table="current_position",
                what="it needs a universe to assess",
            )
        outcome = await resolve_declaration(engine, "stockout_risk", _scope(), as_of=as_of)
        assert isinstance(outcome, DeclarationSatisfied), f"did not resolve: {outcome}"

        universe = await outcome.fetches["current_state"]()
        series = await outcome.fetches["daily_series"]()
        plan = plan_for("stockout_risk")
        assert plan is not None
        planned = await plan(outcome, as_of)
        actions = planned.actions
    finally:
        await engine.dispose()

    from synapse.core.stockout_risk import evaluate_stockout_risk

    thresholds = {t.name: t.days for t in STOCKOUT_RISK.thresholds}
    findings = evaluate_stockout_risk(
        universe,  # type: ignore[arg-type]
        series,  # type: ignore[arg-type]
        window_days=thresholds["window_days"],
        at_risk_below_days=thresholds["at_risk_below_days"],
        stale_after_days=thresholds["stale_after_days"],
        min_observations=GATE_DAYS,
        as_of=as_of,
    )
    print(
        f"\nstockout_risk as_of {as_of}: {len(findings)} positions, "
        f"{sum(1 for f in findings if f.refused_because is None)} assessed, "
        f"{len(actions)} actions. Refusals: {dict(counts_by_reason(findings))}\n"
        f"Recorded on the run row as: {dict(planned.refusals)}"
    )

    assert len(findings) == len(universe), "one row per position, assessed or not"
    assert not any(f.is_at_risk and f.refused_because for f in findings), "a refused row was flagged at risk"
    assert len(actions) <= sum(1 for f in findings if f.is_at_risk), (
        "more actions than at-risk findings: an action came from somewhere other than a finding"
    )

    # THE STALENESS ASSERTION IS CONDITIONAL ON THE DATA ACTUALLY BEING STALE, and that is a
    # correction to how this test was first written. It asserted "every position is refused",
    # which is a property of STAGING'S SNAPSHOT (last sale 2026-07-19) rather than of the code —
    # so it failed the moment it met a database with fresh rows, reporting a guard as broken when
    # the guard was correctly silent. A live test must assert what the code does, not what one
    # dataset happens to look like.
    stale_after = thresholds["stale_after_days"]
    newest = max((row.event_date for row in series), default=None)  # type: ignore[attr-defined]
    if newest is None or (as_of - newest).days > stale_after:
        assert all(f.refused_because is not None for f in findings), (
            f"the newest observation is {newest}, more than {stale_after} days before {as_of}, "
            "so every series is stale and none should have been assessed. A cover figure here "
            "divides today's stock by a rate weeks out of date"
        )
        assert not actions, "a refused row must never become an action"
    else:
        assert any(f.refused_because is None for f in findings), (
            f"the newest observation is {newest}, inside the {stale_after}-day limit, yet every "
            "position was refused. The freshness guard is refusing fresh data"
        )
