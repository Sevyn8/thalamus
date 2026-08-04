"""daily_series against a live canonical, SKIPPED unless a read-only DSN is supplied.

SAME POSTURE AS test_current_state_live.py: the identity is ``synapse_reader`` (USAGE on
canonical, SELECT on exactly two tables, NOSUPERUSER NOBYPASSRLS — the ``dis_mirror_reader``
pattern). Supply SYNAPSE_READER_URL plus SYNAPSE_TEST_TENANT_ID to run it. Against staging
also export ``DIS_EXPECTED_DATABASE=thalamus``, or dis-rls refuses the database outright.

READ THIS BEFORE TRUSTING A GREEN RUN.
======================================

**`make seed` does not write canonical.** It writes one ``config.source_mappings`` row and
explicitly nothing else — ``identity_mirror`` is mirror-sync's, and no fixture anywhere
inserts sale events or positions. Any canonical rows in a local devbox are RESIDUE from
having run the streaming consumer's integration tests against the same volume. That is not a
fixture, it is an accident of history: arbitrary content, no guarantee it is there, and
nobody maintains it. **Anyone reading a green local run as proof of correction-collapse is
reading residue.**

Which is why three of these tests REFUSE TO PASS WITHOUT DATA. They raise
``CanonicalDataRequiredError`` — not skip — following
dis/tests/integration/test_rls_platform_session_guard.py, which refuses to skip when its
stack is absent. A skipped test is quiet; a green test that proved nothing gets BELIEVED, and
that is strictly worse than a red one.

So a clean local stack reports **3 passed, 3 failed**, and the three failures say "no
canonical rows — this test cannot prove anything without data". That is the honest state of
the suite, and it is the signal to point SYNAPSE_READER_URL at staging.

WHAT EACH TEST NEEDS
--------------------
NO DATA REQUIRED — real on an empty database, because what they exercise is the SQL and the
resolution machinery, not the numbers:

- ``test_the_collapse_is_valid_postgres_and_the_rows_project`` — a DISTINCT ON whose
  expressions do not match the leading ORDER BY is a runtime error at zero rows. No compiled
  string assertion can prove that; only Postgres can.
- ``test_an_impossible_threshold_yields_precondition_unmet_with_a_real_measurement``
- ``test_resolve_returns_one_of_exactly_three_outcomes``

DATA REQUIRED — these exist to prove statements about ROWS, and on an empty database each
reduces to ``0 == 0``:

- ``test_the_collapse_yields_exactly_one_row_per_dedup_key``
- ``test_the_probe_measures_per_series_and_not_per_tenant``
- ``test_synapse_reader_is_subject_to_rls``

WHAT NONE OF THEM COVER, because Synapse cannot write a DIS table: that a CORRECTION
collapses to one figure, and that a D65 id-less-source correction does NOT. Both need rows
inserted through the mapping pipeline, and both are already asserted in the streaming
consumer's suite (``test_read_time_dedup.py`` pins the D65 case at two surviving keys).
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from datetime import date, timedelta
from types import MappingProxyType
from typing import Any, assert_never
from uuid import UUID

import pytest
from sqlalchemy import func, select, text

from synapse import registry as registry_module
from synapse.core.capability import (
    DAILY_SERIES,
    CapabilityDescriptor,
    CapabilityScope,
    MinHistoryDays,
)
from synapse.core.resolution import PreconditionUnmet, Satisfied, Unregistered

# Structural alias for the conftest fixture's callable. Declared rather than imported: the
# suite runs under --import-mode=importlib with no __init__.py, so a sibling import of
# conftest is fragile. The fixture itself arrives by name, which is not.
RequireRows = Callable[..., Coroutine[Any, Any, int]]

DSN = os.environ.get("SYNAPSE_READER_URL")
TENANT = os.environ.get("SYNAPSE_TEST_TENANT_ID")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DSN or not TENANT,
        reason=(
            "needs SYNAPSE_READER_URL (a synapse_reader DSN, NOT ithina_dis_user) and "
            "SYNAPSE_TEST_TENANT_ID; against staging also DIS_EXPECTED_DATABASE=thalamus"
        ),
    ),
]

# A window wide enough to include whatever beta data exists. Named here rather than inline
# so every test agrees on the range it is comparing raw counts against.
WINDOW_FROM = date(2020, 1, 1)
WINDOW_TO = date.today() + timedelta(days=1)

# The RLS test reads this OUTSIDE rls_session, on a raw engine, which is the only way to
# observe the no-GUC state. Spelled here rather than taken from the conftest fixture because
# the fixture deliberately only hands back a count-and-refuse helper, never a raw statement.
_COUNT_SALE_EVENTS = text(
    "SELECT COUNT(*) FROM canonical.store_sku_sale_events WHERE tenant_id = CAST(:tenant AS uuid)"
)


def _scope() -> CapabilityScope:
    return CapabilityScope(tenant_id=UUID(str(TENANT)))


async def test_the_collapse_is_valid_postgres_and_the_rows_project() -> None:
    """NO DATA REQUIRED — one of the three that are real on an empty database.

    An empty result is a genuine PASS here, and not vacuously: what is being exercised is
    that the statement EXECUTES. A DISTINCT ON whose expressions do not match the leading
    ORDER BY is a runtime error Postgres raises at zero rows, and no compiled-string
    assertion in the unit suite can tell "matches" from "matches according to my regex".
    A canonical rename fails here too, also at zero rows.

    The per-row assertions below are a bonus when rows happen to exist; they are not what
    this test is for, which is why their absence is not an error.
    """
    from dis_rls import create_rls_engine
    from synapse.resolvers.daily_series import resolve_daily_series

    engine = create_rls_engine(DSN)
    try:
        rows = await resolve_daily_series(
            engine, _scope(), date_from=WINDOW_FROM, date_to=WINDOW_TO, limit=500
        )
    finally:
        await engine.dispose()

    for row in rows:
        assert row.tenant_id == UUID(str(TENANT)), "RLS and the tenant predicate must agree"
        assert isinstance(row.event_date, date)
        counted = row.sale_line_count + row.return_line_count + row.void_line_count
        assert counted > 0, "a group exists because rows exist, so some subtype must be counted"


async def test_the_collapse_yields_exactly_one_row_per_dedup_key(
    require_canonical_rows: RequireRows,
) -> None:
    """THE D33 PROPERTY, checked against raw counts rather than asserted.

    DATA REQUIRED. Counts distinct dedup keys directly, then counts the rows the collapse
    returns; they must be equal. On an empty table that is ``0 == 0``, which would report
    success while proving nothing about the key — so this refuses to run without rows.

    What it catches when there ARE rows: a collapse key narrowed to three columns. That is
    still valid SQL and would merge unrelated source events into one survivor.
    """
    from dis_rls import create_rls_engine, rls_session
    from synapse.resolvers._collapse import DEDUP_KEY, collapse_latest_wins
    from synapse.resolvers.daily_series import (
        _EVENT_TIME_COLUMN,
        _key_scoped_predicate,
        _sale_events,
    )

    scope = _scope()
    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, scope.tenant_id) as conn:
            await require_canonical_rows(
                conn, scope.tenant_id, table="sale_events", what="it compares dedup-key counts"
            )
            distinct_keys = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) FROM (SELECT DISTINCT tenant_id, store_id, source_id, "
                        "source_event_id FROM canonical.store_sku_sale_events "
                        "WHERE tenant_id = CAST(:tenant AS uuid)) keys"
                    ),
                    {"tenant": str(scope.tenant_id)},
                )
            ).scalar_one()

            collapsed = collapse_latest_wins(
                _sale_events,
                event_time_column=_EVENT_TIME_COLUMN,
                where=_key_scoped_predicate(scope, None),
            )
            survivors = (
                await conn.execute(select(func.count()).select_from(collapsed))
            ).scalar_one()
    finally:
        await engine.dispose()

    assert len(DEDUP_KEY) == 4, "the raw query above hardcodes the four key columns"
    assert distinct_keys > 0, "guarded by require_rows; 0 == 0 would prove nothing"
    assert survivors == distinct_keys, (
        f"the collapse returned {survivors} rows for {distinct_keys} distinct dedup keys"
    )


async def test_the_probe_measures_per_series_and_not_per_tenant(
    require_canonical_rows: RequireRows,
) -> None:
    """THE DEFECT TEST, and DATA REQUIRED — without rows it is the defect all over again.

    Counts series and qualifying series raw, then compares. The raw query groups by
    ``(store_id, sku_id)`` and is deliberately written out rather than built from the probe's
    own constants, so a probe that reverted to per-tenant counting disagrees with it instead
    of agreeing with itself.

    On an empty table every comparison is ``0 <= 0`` and a per-TENANT probe would pass this
    test — the exact measurement it exists to catch. Refusing without rows is the only way it
    means anything.

    Coverage, not span: a probe that drifted to MIN/MAX arithmetic would report a larger
    number for any series with a gap in its trading days.
    """
    from dis_rls import create_rls_engine, rls_session
    from synapse.resolvers.daily_series import probe_min_history_days

    scope = _scope()
    required = 60
    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, scope.tenant_id) as conn:
            await require_canonical_rows(
                conn,
                scope.tenant_id,
                table="sale_events",
                what="it compares per-series coverage counts",
            )
        observation = await probe_min_history_days(engine, scope, required=required)
        async with rls_session(engine, scope.tenant_id) as conn:
            raw = (
                await conn.execute(
                    text(
                        "SELECT COUNT(*) AS pairs, "
                        "       COUNT(*) FILTER (WHERE coverage >= :required) AS qualifying "
                        "FROM (SELECT store_id, sku_id, COUNT(DISTINCT event_date) AS coverage "
                        "      FROM canonical.store_sku_sale_events "
                        "      WHERE tenant_id = CAST(:tenant AS uuid) "
                        "      GROUP BY store_id, sku_id) per_series"
                    ),
                    {"tenant": str(scope.tenant_id), "required": required},
                )
            ).one()
            tenant_level = (
                await conn.execute(
                    text(
                        "SELECT COUNT(DISTINCT event_date) FROM canonical.store_sku_sale_events "
                        "WHERE tenant_id = CAST(:tenant AS uuid)"
                    ),
                    {"tenant": str(scope.tenant_id)},
                )
            ).scalar_one()
    finally:
        await engine.dispose()

    # Per-series, and never MORE than the raw count: the probe collapses first, so on a tenant
    # carrying an sku-changing correction it reports fewer series than the raw query, not more.
    assert raw.pairs > 0, "guarded by require_rows; a zero population proves nothing"
    assert observation.pairs_measured > 0, (
        "the probe found no series where the raw per-(store, sku) aggregate found "
        f"{raw.pairs} — it is not measuring at series grain"
    )
    assert observation.pairs_measured <= raw.pairs
    assert observation.pairs_qualifying <= raw.qualifying
    assert observation.measured_at is not None, "the report's timestamp comes from the DB clock"

    if raw.pairs and raw.qualifying == 0:
        # THE STATE THE DEFECT HID: a tenant whose calendar clears the threshold while not one
        # series does. A per-tenant probe would report `tenant_level` here and the gate would
        # pass; the per-series probe reports zero qualifying series and the gate fires.
        assert observation.pairs_qualifying == 0
        print(
            f"per-series: 0 of {observation.pairs_measured} series have {required}+ days; "
            f"per-tenant would have reported {tenant_level}"
        )


async def test_an_impossible_threshold_yields_precondition_unmet_with_a_real_measurement(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE THIRD OUTCOME, END TO END. NO DATA REQUIRED.

    Uses the REAL probe against a deliberately unreachable threshold, so the observation is a
    genuine measurement rather than a stub. Honest at zero rows: 0 of 0 series clearing 10,000
    days IS the correct answer, and the resolution path — probe, report composition, policy,
    outcome type — executes identically either way. This is the case a registry returning
    ``Resolver | None`` collapses into "no such capability".
    """
    from dis_rls import create_rls_engine
    from synapse.registry import ProbeBinding, RegisteredCapability, resolve
    from synapse.resolvers.daily_series import (
        DATE_COLUMN,
        SERIES_GRAIN,
        probe_min_history_days,
        resolve_daily_series,
    )

    impossible = CapabilityDescriptor(
        id=DAILY_SERIES.id,
        version=DAILY_SERIES.version,
        grain=DAILY_SERIES.grain,
        tenancy=DAILY_SERIES.tenancy,
        freshness=DAILY_SERIES.freshness,
        returns=DAILY_SERIES.returns,
        produces_signals=DAILY_SERIES.produces_signals,
        preconditions=(MinHistoryDays(days=10_000),),
    )
    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        MappingProxyType(
            {
                impossible.id: RegisteredCapability(
                    descriptor=impossible,
                    resolver=resolve_daily_series,
                    probes=MappingProxyType(
                        {
                            MinHistoryDays.name: ProbeBinding(
                                measure=probe_min_history_days,
                                series_grain=SERIES_GRAIN,
                                date_column=DATE_COLUMN,
                            )
                        }
                    ),
                )
            }
        ),
    )

    engine = create_rls_engine(DSN)
    try:
        outcome = await resolve(engine, "daily_series", _scope())
    finally:
        await engine.dispose()

    assert isinstance(outcome, PreconditionUnmet)
    (report,) = outcome.unmet
    assert report.required == 10_000
    assert report.pairs_qualifying == 0, "no series has 10,000 days of history"
    assert report.pairs_measured >= 0, "a real count of series, even if the tenant has none"


async def test_resolve_returns_one_of_exactly_three_outcomes() -> None:
    """The console's branch, against the real registry and a real database. NO DATA REQUIRED.

    Whichever outcome arrives is a real one. On the current beta tenant it is PreconditionUnmet
    (~9 observations per series against 60), and on an empty database it is also
    PreconditionUnmet (0 of 0) — different reasons, same branch, and the branch is what is
    under test.
    """
    from dis_rls import create_rls_engine
    from synapse.registry import resolve

    engine = create_rls_engine(DSN)
    try:
        outcome = await resolve(
            engine, "daily_series", _scope(), date_from=WINDOW_FROM, date_to=WINDOW_TO
        )
    finally:
        await engine.dispose()

    match outcome:
        case Satisfied():
            assert outcome.descriptor.id == "daily_series"
        case PreconditionUnmet():
            # The EXPECTED outcome on the current beta tenant, and expected is the point: ~9
            # observations per series against a 60-day requirement means no series qualifies.
            # That is the gate working. The honest answer is that this data cannot support a
            # per-SKU forecast, and it is better to learn that here than from a forecast.
            report = outcome.unmet[0]
            assert report.required == 60
            assert report.pairs_qualifying == 0
            print(
                f"daily_series blocked: {report.pairs_qualifying} of {report.pairs_measured} "
                f"series have {report.required}+ days of observations"
            )
        case Unregistered():  # pragma: no cover - it is in the registry
            pytest.fail("daily_series is registered; this outcome means the registry moved")
        case _:  # pragma: no cover
            assert_never(outcome)


async def test_synapse_reader_is_subject_to_rls(require_canonical_rows: RequireRows) -> None:
    """DATA REQUIRED. The whole point of the role: RLS BITES for it.

    This is the check_setup.sh:294 pattern as a test, and it is the only one here that
    distinguishes the three situations an operator cannot tell apart from a result set:

        missing GRANT        -> ERROR: permission denied      (loud, distinguishable)
        GUCs not set         -> 0 rows, silently
        tenant has no data   -> 0 rows, silently

    The last two are identical from the outside, which is why this refuses to run on an empty
    table: without rows, "0 with no GUCs" is exactly what a BYPASSRLS role would also return,
    and the test would certify the opposite of what it claims.

    So: prove rows are visible WITH the GUCs, then prove the same query returns zero WITHOUT
    them. Both halves, in that order, or neither means anything.

    dis-rls's own posture guard (rolsuper/rolbypassrls from pg_roles) is the loud backstop and
    fires on the first query of every test in this file. This checks the quiet half it cannot:
    that the POLICIES actually exclude rows for this role.
    """
    from sqlalchemy.ext.asyncio import create_async_engine

    from dis_rls import create_rls_engine, rls_session

    scope = _scope()
    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, scope.tenant_id) as conn:
            with_gucs = await require_canonical_rows(
                conn, scope.tenant_id, table="sale_events", what="it proves RLS excludes rows"
            )
    finally:
        await engine.dispose()

    # A RAW engine, deliberately outside rls_session — the only way to observe the no-GUC
    # state, since rls_session always sets both. Not a pattern to copy into resolvers; it is
    # here precisely to prove what happens to code that does.
    raw = create_async_engine(str(DSN))
    try:
        async with raw.connect() as conn:
            no_gucs = (
                await conn.execute(_COUNT_SALE_EVENTS, {"tenant": str(scope.tenant_id)})
            ).scalar_one()
    finally:
        await raw.dispose()

    assert with_gucs > 0, "guarded above; without visible rows the next assertion proves nothing"
    assert no_gucs == 0, (
        f"synapse_reader read {no_gucs} rows with no app.tenant_id / app.user_type set, while "
        f"the same query under rls_session returned {with_gucs}. RLS IS NOT ENFORCED for this "
        "role - check rolbypassrls and that FORCE ROW LEVEL SECURITY is still on the table"
    )
