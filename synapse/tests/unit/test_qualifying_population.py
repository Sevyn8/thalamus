"""The qualifying-population fix, and the trap inside it.

SLICE 2 DEFERRED THIS WITH A SELF-NAMING TRIGGER — "the first analysis that binds a gate" — and
``stockout_risk`` is that analysis. Before the fix, an ANY_SERIES gate that passed 46 of 65
series would hand back a fetch returning all 65, so the analysis computed cover for series it had
just declared unfit.

THE DANGEROUS HALF IS NOT THE FIX, IT IS THE GATELESS CASE. ``dead_stock`` measures no population
at all, so it must be narrowed to NOTHING — meaning "no narrowing", not "narrow to the empty
set". Conflating those turns dead_stock into an analysis that returns zero rows for ever while
still reporting Satisfied. Three separate things prevent it and each is tested here:

  - ``Satisfied`` refuses to hold an empty qualifying tuple at all
  - ``resolve_daily_series`` refuses an empty ``only_series``
  - ``None`` flows through both as "everything in scope"
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, date, datetime

import pytest

from synapse.core.capability import CURRENT_STATE, DAILY_SERIES
from synapse.core.resolution import Observation, Satisfied

MEASURED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=UTC)


async def _nothing() -> Sequence[object]:
    return ()


# ---------------------------------------------------------------------------
# Satisfied: None is unmeasured, () is unrepresentable
# ---------------------------------------------------------------------------


def test_a_gateless_capability_resolves_with_no_narrowing() -> None:
    """dead_stock's shape. None means nothing was measured, so nothing is narrowed."""
    satisfied = Satisfied(descriptor=CURRENT_STATE, fetch=_nothing)
    assert satisfied.qualifying is None


def test_an_empty_qualifying_population_cannot_be_constructed() -> None:
    """THE TRAP, CLOSED. An empty tuple would narrow every fetch to nothing while reporting
    success — an analysis that silently produces nothing, for ever.

    It is unreachable today: ANY_SERIES needs pairs_qualifying > 0 and ALL_SERIES needs
    pairs_measured > 0 with equality, so no policy admits zero. This guards against a THIRD
    policy arriving that does, where the failure would otherwise be silent and total.
    """
    with pytest.raises(ValueError, match="EMPTY qualifying population"):
        Satisfied(descriptor=DAILY_SERIES, fetch=_nothing, qualifying=())


def test_a_populated_qualifying_set_is_carried() -> None:
    """The baseline. Without it the refusal above would also pass against a class that rejected
    every qualifying value."""
    subjects = (("t", "s", "SKU-1"), ("t", "s", "SKU-2"))
    satisfied = Satisfied(descriptor=DAILY_SERIES, fetch=_nothing, qualifying=subjects)
    assert satisfied.qualifying == subjects


# ---------------------------------------------------------------------------
# Observation: the counts and the identities must agree
# ---------------------------------------------------------------------------


def test_an_observation_may_report_counts_without_identities() -> None:
    """No probe is in this state today. The field is Optional so a future probe measuring
    something with no enumerable subject is not forced to invent one."""
    assert Observation(pairs_measured=65, pairs_qualifying=46, measured_at=MEASURED_AT)


def test_identities_disagreeing_with_the_count_is_refused() -> None:
    """The two come from ONE transaction, so a mismatch is a bug rather than a race. Left
    unchecked it would narrow a fetch to a population the verdict was not made about — the exact
    thing the fix exists to prevent, reintroduced by an off-by-one."""
    with pytest.raises(ValueError, match="qualifying series but returned"):
        Observation(
            pairs_measured=65,
            pairs_qualifying=46,
            measured_at=MEASURED_AT,
            qualifying=(("t", "s", "SKU-1"),),
        )


def test_matching_identities_are_accepted() -> None:
    observation = Observation(
        pairs_measured=2,
        pairs_qualifying=2,
        measured_at=MEASURED_AT,
        qualifying=(("t", "s", "A"), ("t", "s", "B")),
    )
    assert observation.qualifying is not None and len(observation.qualifying) == 2


# ---------------------------------------------------------------------------
# The resolver's narrowing
# ---------------------------------------------------------------------------


async def test_the_resolver_refuses_an_empty_narrowing() -> None:
    """The second place the empty set cannot pass. A caller that computed an empty population
    and passed it would otherwise get zero rows and no error."""
    from uuid import UUID

    from synapse.core.capability import CapabilityScope
    from synapse.resolvers.daily_series import resolve_daily_series

    with pytest.raises(ValueError, match="only_series is empty"):
        await resolve_daily_series(
            None,  # type: ignore[arg-type]
            CapabilityScope(tenant_id=UUID(int=1)),
            date_from=MEASURED_AT.date(),
            date_to=MEASURED_AT.date(),
            only_series=(),
        )


async def test_the_resolver_refuses_a_narrowing_larger_than_it_will_render() -> None:
    """An IN-list is linear in the population. Raising rather than truncating: a shortened list
    would silently exclude series that DID qualify."""
    from uuid import UUID

    from synapse.core.capability import CapabilityScope
    from synapse.core.errors import ResultTooLargeError
    from synapse.resolvers.daily_series import _MAX_SERIES, resolve_daily_series

    too_many = tuple(("t", "s", f"SKU-{n}") for n in range(_MAX_SERIES + 1))
    with pytest.raises(ResultTooLargeError, match="IN-list"):
        await resolve_daily_series(
            None,  # type: ignore[arg-type]
            CapabilityScope(tenant_id=UUID(int=1)),
            date_from=MEASURED_AT.date(),
            date_to=MEASURED_AT.date(),
            only_series=too_many,
        )


# ---------------------------------------------------------------------------
# The window declaration, and the contradiction the registry refuses
# ---------------------------------------------------------------------------


def test_stockout_risk_declares_a_window_and_dead_stock_does_not() -> None:
    """The field is Optional because most requirements take no window. If dead_stock ever
    acquired one, resolve_declaration would start demanding an as_of it has never needed."""
    from synapse.core.analysis import DEAD_STOCK, STOCKOUT_RISK

    assert all(r.window_from_threshold is None for r in DEAD_STOCK.requires)
    windows = {r.capability_id: r.window_from_threshold for r in STOCKOUT_RISK.requires}
    assert windows == {"current_state": None, "daily_series": "window_days"}


def test_a_window_naming_a_threshold_that_does_not_exist_is_refused() -> None:
    """PROVE THE GUARD FIRES. Otherwise the KeyError surfaces inside resolve_declaration, at the
    first fetch, for one tenant."""
    from dataclasses import replace
    from types import MappingProxyType

    import synapse.registry as registry_module
    from synapse.core.analysis import STOCKOUT_RISK

    broken = replace(
        STOCKOUT_RISK,
        requires=tuple(
            replace(r, window_from_threshold="no_such_threshold") if r.capability_id == "daily_series" else r
            for r in STOCKOUT_RISK.requires
        ),
    )
    with pytest.raises(ValueError, match="declares no threshold by that name"):
        registry_module.check_window_declarations(
            MappingProxyType({broken.id: broken}), registry_module._REGISTRY
        )


def test_a_window_against_a_last_write_capability_is_refused() -> None:
    """THE CHECK THAT PROVES THIS FIELD IS THE OPERATIONAL HALF OF ``freshness``.

    ``Freshness`` has said since slice 1 which capabilities a date parameter is meaningful for.
    LAST_WRITE means asking for a past date is not answerable, so a window against one is a
    question the capability's own contract says has no answer — and it would pass a date_from
    the resolver does not accept. A field that could be declared anywhere would be a parameter
    bolted on; one that must agree with an existing contract field is its counterpart.
    """
    from dataclasses import replace
    from types import MappingProxyType

    import synapse.registry as registry_module
    from synapse.core.analysis import STOCKOUT_RISK
    from synapse.core.capability import Freshness

    assert CURRENT_STATE.freshness is Freshness.LAST_WRITE, "the fixture must be LAST_WRITE"
    contradiction = replace(
        STOCKOUT_RISK,
        requires=tuple(
            replace(r, window_from_threshold="window_days") if r.capability_id == "current_state" else r
            for r in STOCKOUT_RISK.requires
        ),
    )
    with pytest.raises(ValueError, match="only meaningful for AS_OF_DATE"):
        registry_module.check_window_declarations(
            MappingProxyType({contradiction.id: contradiction}), registry_module._REGISTRY
        )


def test_the_real_registry_passes_the_window_check() -> None:
    """The baseline. Without it the two refusals above would pass against a check that raised
    unconditionally."""
    import synapse.registry as registry_module

    registry_module.check_window_declarations(registry_module._DECLARATIONS, registry_module._REGISTRY)


# ---------------------------------------------------------------------------
# The narrowing must actually REACH the resolver
# ---------------------------------------------------------------------------
#
# NOTHING ABOVE PROVED THIS, and finding that out is why the section exists. Deleting the line
# in resolve() that forwards `only_series` left all 331 tests green: the types were verified, the
# refusals were verified, and the one step that carries the population from the probe to the
# query was covered by nothing. That is the whole fix, untested.


class _Recorder:
    """A resolver that records the keyword arguments resolve() handed it.

    A test DOUBLE, not a reimplementation. What is under test is what resolve() FORWARDS; this
    returns nothing and asserts nothing itself.
    """

    def __init__(self) -> None:
        self.kwargs: dict[str, object] | None = None

    async def __call__(self, engine: object, scope: object, **kwargs: object) -> Sequence[object]:
        self.kwargs = kwargs
        return ()


def _probe_returning(subjects: tuple[tuple[str, ...], ...]) -> object:
    async def measure(engine: object, scope: object, **kwargs: object) -> Observation:
        return Observation(
            pairs_measured=len(subjects) + 1,
            pairs_qualifying=len(subjects),
            measured_at=MEASURED_AT,
            qualifying=subjects,
        )

    return measure


async def test_resolve_forwards_the_qualifying_population_to_the_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE STEP THE WHOLE FIX RESTS ON. The probe measured 2 of 3; the resolver must be told to
    fetch those 2 and no others."""
    from types import MappingProxyType
    from uuid import UUID

    import synapse.registry as registry_module
    from synapse.core.analysis import MinHistoryDays
    from synapse.core.capability import CapabilityScope, GateKind
    from synapse.core.resolution import SeriesPolicy

    subjects = (("t", "s", "SKU-1"), ("t", "s", "SKU-2"))
    recorder = _Recorder()
    entry = registry_module.RegisteredCapability(
        descriptor=DAILY_SERIES,
        resolver=recorder,
        probes=MappingProxyType(
            {
                GateKind.MIN_HISTORY_DAYS: registry_module.ProbeBinding(
                    measure=_probe_returning(subjects),  # type: ignore[arg-type]
                    series_grain=("tenant_id", "store_id", "sku_id"),
                    date_column="event_date",
                )
            }
        ),
    )
    monkeypatch.setattr(registry_module, "_REGISTRY", MappingProxyType({DAILY_SERIES.id: entry}))

    outcome = await registry_module.resolve(
        None,  # type: ignore[arg-type]
        DAILY_SERIES.id,
        CapabilityScope(tenant_id=UUID(int=1)),
        gates=(MinHistoryDays(days=7, policy=SeriesPolicy.ANY_SERIES),),
    )
    assert isinstance(outcome, Satisfied)
    assert outcome.qualifying == subjects, "Satisfied must carry the population for inspection"

    await outcome.fetch()
    assert recorder.kwargs is not None
    assert recorder.kwargs.get("only_series") == subjects, (
        "the narrowing did not reach the resolver: a caller gets rows for series the gate "
        "refused, which is the bug this fix exists to remove"
    )


async def test_a_gateless_capability_forwards_no_narrowing_at_all(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dead_stock's path, and it must not merely be None — the key must be ABSENT.

    ``resolve_current_state`` has no ``only_series`` parameter, so forwarding the key at all
    would be a TypeError on every dead_stock fetch. That is loud rather than silent, but it is
    still a regression this catches at unit speed instead of in a staging window.
    """
    from types import MappingProxyType
    from uuid import UUID

    import synapse.registry as registry_module
    from synapse.core.capability import CapabilityScope

    recorder = _Recorder()
    entry = registry_module.RegisteredCapability(
        descriptor=CURRENT_STATE, resolver=recorder, probes=MappingProxyType({})
    )
    monkeypatch.setattr(registry_module, "_REGISTRY", MappingProxyType({CURRENT_STATE.id: entry}))

    outcome = await registry_module.resolve(
        None,  # type: ignore[arg-type]
        CURRENT_STATE.id,
        CapabilityScope(tenant_id=UUID(int=1)),
        gates=(),
    )
    assert isinstance(outcome, Satisfied)
    assert outcome.qualifying is None

    await outcome.fetch()
    assert recorder.kwargs is not None
    assert "only_series" not in recorder.kwargs, (
        "a gateless capability was handed a narrowing keyword its resolver cannot accept"
    )


async def test_resolve_declaration_computes_and_forwards_the_date_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """THE TEST WHOSE ABSENCE LET A MISSING EDIT SHIP.

    The window computation in ``resolve_declaration`` was written, silently failed to apply, and
    nothing noticed: mypy was happy, 333 unit tests passed, and the failure surfaced only when a
    live test called a bound fetch and got ``TypeError: missing 2 required keyword-only
    arguments``. Nothing offline had ever asserted that a declared window reaches the resolver.

    Uses the REAL declaration, so the threshold and the arithmetic are the ones production uses.
    """
    from types import MappingProxyType
    from uuid import UUID

    import synapse.registry as registry_module
    from synapse.core.analysis import STOCKOUT_RISK
    from synapse.core.capability import CURRENT_STATE, CapabilityScope, GateKind
    from synapse.core.declaration_resolution import DeclarationSatisfied

    subjects = (("t", "s", "SKU-1"),)
    series_recorder, state_recorder = _Recorder(), _Recorder()
    monkeypatch.setattr(
        registry_module,
        "_REGISTRY",
        MappingProxyType(
            {
                DAILY_SERIES.id: registry_module.RegisteredCapability(
                    descriptor=DAILY_SERIES,
                    resolver=series_recorder,
                    probes=MappingProxyType(
                        {
                            GateKind.MIN_HISTORY_DAYS: registry_module.ProbeBinding(
                                measure=_probe_returning(subjects),  # type: ignore[arg-type]
                                series_grain=("tenant_id", "store_id", "sku_id"),
                                date_column="event_date",
                            )
                        }
                    ),
                ),
                CURRENT_STATE.id: registry_module.RegisteredCapability(
                    descriptor=CURRENT_STATE, resolver=state_recorder, probes=MappingProxyType({})
                ),
            }
        ),
    )

    as_of = date(2026, 8, 5)
    outcome = await registry_module.resolve_declaration(
        None,  # type: ignore[arg-type]
        "stockout_risk",
        CapabilityScope(tenant_id=UUID(int=1)),
        as_of=as_of,
    )
    assert isinstance(outcome, DeclarationSatisfied), outcome

    await outcome.fetches["daily_series"]()
    assert series_recorder.kwargs is not None
    window_days = next(t.days for t in STOCKOUT_RISK.thresholds if t.name == "window_days")
    assert series_recorder.kwargs.get("date_to") == as_of
    assert series_recorder.kwargs.get("date_from") == date(2026, 7, 9), (
        f"a {window_days}-day window ending {as_of} starts on the 9th, inclusive at both ends"
    )

    await outcome.fetches["current_state"]()
    assert state_recorder.kwargs is not None
    assert "date_from" not in state_recorder.kwargs, (
        "current_state declares no window and its resolver takes none; forwarding one would be "
        "a TypeError on every fetch"
    )


async def test_resolve_declaration_refuses_a_window_without_an_as_of() -> None:
    """A window is relative to the moment of asking. Omitting as_of raises here, naming the
    analysis, rather than surfacing as a missing-keyword TypeError at the first fetch."""
    from uuid import UUID

    from synapse.core.capability import CapabilityScope
    from synapse.registry import resolve_declaration

    with pytest.raises(ValueError, match="needs as_of"):
        await resolve_declaration(
            None,  # type: ignore[arg-type]
            "stockout_risk",
            CapabilityScope(tenant_id=UUID(int=1)),
        )
