"""The refusal breakdown, from the evaluator's branch to the bytes stored on synapse.run.

WHAT THIS SLICE CLOSED. ``actions_proposed = 0`` meant either "looked and found nothing" or
"could not assess anything" — most often because every series was refused as stale — and nothing
in the row told them apart. The console shipped a third rendering state meaning "zero, and we
cannot tell which", and a tenant-page row describing this exact gap was deleted in Phase A rather
than left claiming knowledge it did not have.

THE HAZARD THIS FILE GUARDS IS NOT "does the number arrive". It is that the STORED KEYS must be
stable: ``synapse.run`` is not append-only (run.sql:44 records the absence of the trigger as a
decision), so a re-run of a slot may rewrite the row, and the correctness rule is that the same
slot over the same data produces the same bytes. Two things could break that and both are tested
below — a vocabulary derived from prose that interpolates dates, and a dict whose key order
follows the order positions happened to be refused in.
"""

from __future__ import annotations

import inspect
import json
import re
from collections.abc import Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from uuid import UUID

import pytest

from synapse.core.current_state import CurrentStateRow
from synapse.core.daily_series import DailySeriesRow
from synapse.core.stockout_risk import (
    RefusalReason,
    StockoutRiskRow,
    counts_by_reason,
    evaluate_stockout_risk,
)

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
AS_OF = date(2026, 8, 7)


def _position(sku_id: str, stock: Decimal | None = Decimal("40.000")) -> CurrentStateRow:
    return CurrentStateRow(
        tenant_id=TENANT,
        store_id=STORE,
        sku_id=sku_id,
        product_name=sku_id,
        product_category=None,
        sku_status="ACTIVE",
        current_retail_price=Decimal("89.0000"),
        unit_cost=None,
        promo_price=None,
        stock_qty=stock,
        reorder_point=None,
        currency="INR",
        expiry_date=None,
        last_source_event_at=None,
        last_updated_at=datetime(2026, 8, 4, tzinfo=UTC),
    )


def _obs(sku_id: str, when: date, qty: str = "5.000") -> DailySeriesRow:
    return DailySeriesRow(
        tenant_id=TENANT,
        store_id=STORE,
        sku_id=sku_id,
        event_date=when,
        net_quantity=Decimal(qty),
        sale_line_count=1,
        return_line_count=0,
        void_line_count=0,
    )


def _evaluate(universe: list[CurrentStateRow], series: list[DailySeriesRow], *, as_of: date = AS_OF):  # type: ignore[no-untyped-def]
    return evaluate_stockout_risk(
        universe,
        series,
        window_days=30,
        at_risk_below_days=14,
        stale_after_days=7,
        min_observations=3,
        as_of=as_of,
    )


# ---------------------------------------------------------------------------
# The vocabulary is closed, and every branch has a member
# ---------------------------------------------------------------------------


def test_every_refusal_branch_returns_a_vocabulary_member() -> None:
    """NO FREE-TEXT KEY MAY REACH THE BREAKDOWN. Parsed from the source rather than exercised, so
    a NEW branch added later is caught even if no test drives it: every `return (` inside
    ``_refusal`` must name a RefusalReason.
    """
    # _refusal MOVED to core/cover.py in M1: overstock reads the same quotient from the
    # other tail, so the computation and its refusal order are shared rather than copied.
    from synapse.core import cover

    source = inspect.getsource(cover._refusal)
    returns = [m for m in re.findall(r"return \(\s*([A-Za-z_.]+)", source)]
    assert returns, "no tuple returns parsed from _refusal; the regex stopped biting"
    for returned in returns:
        assert returned.startswith("RefusalReason."), (
            f"_refusal returns {returned!r}, which is not a RefusalReason member. A free-text "
            "reason would become a stored key that cannot be grouped and varies per slot."
        )


def test_the_vocabulary_has_no_unused_members() -> None:
    """The other direction: a member nobody produces is a promise the data never keeps, and a
    console branch for it would be dead code that reads as coverage."""
    # _refusal MOVED to core/cover.py in M1: overstock reads the same quotient from the
    # other tail, so the computation and its refusal order are shared rather than copied.
    from synapse.core import cover

    source = inspect.getsource(cover._refusal)
    for member in RefusalReason:
        assert f"RefusalReason.{member.name}" in source, (
            f"{member.name} is declared but no branch produces it"
        )


def test_a_row_cannot_carry_prose_without_a_category() -> None:
    """The two halves are pinned to each other, so a stored breakdown and the row a reader opens
    can never disagree about whether a position was assessed."""
    with pytest.raises(ValueError, match="must carry BOTH"):
        StockoutRiskRow(
            tenant_id=TENANT,
            store_id=STORE,
            sku_id="SKU-1",
            days_of_cover=None,
            is_at_risk=False,
            refused_because="stale",
            refusal_reason=None,
        )


def test_a_row_cannot_carry_a_category_without_prose() -> None:
    """The mirror. The prose carries the per-series specifics an operator acts on; a category
    alone would be a count with no evidence behind it."""
    with pytest.raises(ValueError, match="must carry BOTH"):
        StockoutRiskRow(
            tenant_id=TENANT,
            store_id=STORE,
            sku_id="SKU-1",
            days_of_cover=None,
            is_at_risk=False,
            refused_because=None,
            refusal_reason=RefusalReason.SERIES_TOO_STALE,
        )


# ---------------------------------------------------------------------------
# The breakdown itself
# ---------------------------------------------------------------------------


def test_the_dominant_case_is_counted_as_stale() -> None:
    """THE REAL ONE. Every rate-based analysis refuses series older than its freshness threshold,
    and on this data that is what a zero-action run almost always means."""
    universe = [_position("SKU-A"), _position("SKU-B")]
    series = [_obs("SKU-A", date(2026, 7, 20)), _obs("SKU-B", date(2026, 7, 21))]

    counts = counts_by_reason(_evaluate(universe, series))

    assert counts == {RefusalReason.SERIES_TOO_STALE: 2}


def test_distinct_reasons_are_counted_separately() -> None:
    universe = [_position("SKU-STALE"), _position("SKU-NOSTOCK", stock=None), _position("SKU-NONE")]
    series = [_obs("SKU-STALE", date(2026, 7, 20))]

    counts = counts_by_reason(_evaluate(universe, series))

    assert counts == {
        RefusalReason.SERIES_TOO_STALE: 1,
        RefusalReason.NO_STOCK_QUANTITY: 1,
        RefusalReason.NO_OBSERVATIONS_IN_WINDOW: 1,
    }


def test_an_all_assessed_run_yields_an_empty_map_not_a_map_of_zeros() -> None:
    """`{}` is what "the plan ran and refused nothing" serialises to. A map of zeros would make
    every run look like it had something to explain."""
    universe = [_position("SKU-OK")]
    series = [_obs("SKU-OK", AS_OF), _obs("SKU-OK", date(2026, 8, 6)), _obs("SKU-OK", date(2026, 8, 5))]

    assert counts_by_reason(_evaluate(universe, series)) == {}


def test_assessed_positions_are_not_counted() -> None:
    """The denominator stays honest: only refused rows appear."""
    universe = [_position("SKU-OK"), _position("SKU-STALE")]
    series = [
        _obs("SKU-OK", AS_OF),
        _obs("SKU-OK", date(2026, 8, 6)),
        _obs("SKU-OK", date(2026, 8, 5)),
        _obs("SKU-STALE", date(2026, 7, 20)),
    ]

    assert counts_by_reason(_evaluate(universe, series)) == {RefusalReason.SERIES_TOO_STALE: 1}


# ---------------------------------------------------------------------------
# Re-run stability — the rule synapse.run's mutability makes load-bearing
# ---------------------------------------------------------------------------


def test_the_same_slot_over_the_same_data_yields_an_identical_breakdown() -> None:
    """SYNAPSE.RUN IS NOT APPEND-ONLY. run.sql:44 records the absence of the trigger as a
    decision: a row is the state of an ATTEMPT, and a takeover after a crash rewrites it. So the
    rule is not "written once" but "the same slot re-run produces the same bytes"."""
    universe = [_position("SKU-A"), _position("SKU-B"), _position("SKU-C", stock=None)]
    series = [_obs("SKU-A", date(2026, 7, 20)), _obs("SKU-B", date(2026, 7, 21))]

    first = counts_by_reason(_evaluate(universe, series))
    second = counts_by_reason(_evaluate(universe, series))

    assert first == second
    assert _stored(first) == _stored(second)


def test_the_stored_form_is_key_sorted_regardless_of_refusal_order() -> None:
    """THE ONE A DICT WOULD BREAK QUIETLY. Python dicts preserve INSERTION order, which follows
    the order positions were refused in — so the same counts reached by a different universe
    ordering would serialise to different bytes and compare unequal as text. The recorder sorts;
    this proves sorting is what makes the two orderings agree.
    """
    stale, nostock = _position("SKU-STALE"), _position("SKU-NOSTOCK", stock=None)
    series = [_obs("SKU-STALE", date(2026, 7, 20))]

    one = counts_by_reason(_evaluate([stale, nostock], series))
    other = counts_by_reason(_evaluate([nostock, stale], series))

    assert list(one) != list(other), "the fixture no longer produces two different insertion orders"
    assert _stored(one) == _stored(other)


def test_the_recorder_sorts_the_keys_it_stores() -> None:
    """The sort lives in the persistence layer, so assert it there rather than trusting the call
    site. Reading the source because exercising it needs a database; the behaviour it encodes is
    pinned by the byte-equality assertions above."""
    source = Path(__file__).resolve().parents[2] / "src" / "synapse" / "persistence" / "run_postgres.py"
    body = source.read_text(encoding="utf-8")
    assert "json.dumps(dict(sorted(refusals.items())))" in body, (
        "the recorder no longer sorts the breakdown before storing it; a re-run of the same slot "
        "can now write different bytes for the same counts"
    )


def _stored(counts: Mapping[RefusalReason, int]) -> str:
    """Exactly what run_postgres.complete serialises — sorted keys, JSON text."""
    return json.dumps(dict(sorted(counts.items())))


# ---------------------------------------------------------------------------
# The value reaches the write path
# ---------------------------------------------------------------------------


def test_the_completion_statement_writes_the_column() -> None:
    """The SQL is the seam. A breakdown computed and never written is the same as no breakdown,
    and nothing else in the suite would notice."""
    from synapse.persistence.run_postgres import _COMPLETE

    sql = str(_COMPLETE)
    assert "refusals = CAST(:refusals AS jsonb)" in sql


def test_the_write_path_always_produces_a_json_object_never_null() -> None:
    """THE COLUMN IS NOT NULL (migration 0005). An earlier draft made it nullable and gave NULL a
    third meaning — "the run never reached its plan" — that nothing ever wrote: the runner
    initialises the map and passes it on every path, so a blocked run stored '{}' regardless. The
    prose was the wrong source of truth, and this pins the one that is left.

    "Why did this run assess nothing" is answered by ``outcome``, not by a second encoding here.
    """
    assert _serialise({}) == "{}"
    assert _serialise({RefusalReason.SERIES_TOO_STALE: 2}) == '{"series_too_stale": 2}'


def test_the_recorder_defaults_to_an_empty_map_not_none() -> None:
    """A caller that omits the argument must not write NULL into a NOT NULL column."""
    import inspect

    from synapse.persistence.run_postgres import PostgresRunRecorder

    default = inspect.signature(PostgresRunRecorder.complete).parameters["refusals"].default
    assert default is not None, "a None default would violate the NOT NULL column"
    assert dict(default) == {}


def _serialise(refusals: Mapping[RefusalReason, int]) -> str:
    """Mirrors run_postgres.complete's parameter construction."""
    return json.dumps(dict(sorted(refusals.items())))


def test_the_enum_serialises_to_its_own_value_as_a_json_key() -> None:
    """StrEnum, so no custom encoder. A plain Enum would store "RefusalReason.SERIES_TOO_STALE"
    and the console would render an implementation detail."""
    assert json.dumps({RefusalReason.SERIES_TOO_STALE: 1}) == '{"series_too_stale": 1}'
