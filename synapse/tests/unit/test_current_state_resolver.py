"""The current_state resolver, offline. No DB, no engine.

The load-bearing tests here are the two about VALIDATION, because that is the whole
reason the resolver selects all 45 columns instead of the 12 it projects: a narrow
select cannot be validated against the full canonical model, so narrowing would
silently discard the loud-failure property.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import UUID

import pytest
from pydantic import ValidationError

from dis_canonical import StoreSkuCurrentPosition
from synapse.core.capability import CURRENT_STATE, CapabilityScope, Freshness, Tenancy
from synapse.core.current_state import CurrentStateRow
from synapse.resolvers.current_state import _COLUMNS, _project, _validated

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")


def _row(**overrides: object) -> dict[str, object]:
    """A canonical row with every one of the 45 fields present.

    Built from the MODEL's field list rather than typed out, so this helper cannot
    drift from canonical either.
    """
    base: dict[str, object] = dict.fromkeys(_COLUMNS)
    base.update(
        {
            "id": UUID("019e5e3c-0000-7000-8000-000000000001"),
            "tenant_id": TENANT,
            "store_id": STORE,
            "sku_id": "SKU-000123",
            "product_name": "Oat Milk 1L",
            "current_retail_price": Decimal("89.0000"),
            "tax_treatment": "EXCLUSIVE",
            "currency": "INR",
            "mapping_version_id": 7,
            "trace_id": UUID("019e5e3c-0000-7000-8000-0000000000ff"),
            "dis_channel": "csv_upload",
            "last_updated_at": datetime(2026, 7, 31, 10, 0, tzinfo=UTC),
        }
    )
    base.update(overrides)
    return base


def test_the_select_covers_every_canonical_field() -> None:
    """45 columns, derived from the model — never hand-listed."""
    assert set(_COLUMNS) == set(StoreSkuCurrentPosition.model_fields)
    assert len(_COLUMNS) == 45


def test_a_full_row_validates_and_projects() -> None:
    row = _project(_validated(_row()))
    assert isinstance(row, CurrentStateRow)
    assert row.tenant_id == TENANT
    assert row.sku_id == "SKU-000123"
    assert row.current_retail_price == Decimal("89.0000")


def test_a_missing_canonical_column_fails_loudly() -> None:
    """LOAD-BEARING: a canonical DROP/RENAME must fail on the first row.

    This is what a narrow SELECT would have thrown away. If this ever passes with a
    field removed, the resolver has started tolerating a moved schema and will return
    plausible-but-wrong rows instead of erroring.
    """
    incomplete = _row()
    del incomplete["current_retail_price"]
    with pytest.raises(ValidationError):
        _validated(incomplete)


def test_an_added_canonical_column_fails_loudly() -> None:
    """LOAD-BEARING: extra='forbid' means an ADDED column is caught too.

    The asymmetry matters. A removed column breaks a required field, but an ADDED one
    would sail through a permissive model — and a new canonical column is the more
    likely change. This pins the direction that is easy to miss.
    """
    with pytest.raises(ValidationError):
        _validated(_row(newly_added_canonical_column="surprise"))


def test_the_projection_drops_dis_write_side_provenance() -> None:
    """mapping_version_id / trace_id / ingest_metadata / dis_channel are DIS's concern."""
    fields = set(CurrentStateRow.__dataclass_fields__)
    for leaked in ("mapping_version_id", "trace_id", "ingest_metadata", "dis_channel", "id"):
        assert leaked not in fields, f"{leaked} must not reach the analytics plane"


def test_the_projection_drops_the_unwritten_signal_columns() -> None:
    """The three signal columns are always NULL because nothing writes them.

    Passing them through would hand every consumer three fields that look like missing
    data rather than absent producers.
    """
    fields = set(CurrentStateRow.__dataclass_fields__)
    for signal in ("velocity_7day", "stock_age_days", "unit_cost_trend_30day"):
        assert signal not in fields


def test_projection_and_descriptor_agree_on_returns() -> None:
    """The descriptor's `returns` must BE the projection, not a parallel list."""
    assert set(CURRENT_STATE.returns) == set(CurrentStateRow.__dataclass_fields__)


def test_descriptor_matches_the_committed_fixture() -> None:
    """The Python descriptor and the contract fixture must not drift apart."""
    import json
    import pathlib

    fixture = json.loads(
        (
            pathlib.Path(__file__).resolve().parents[3]
            / "contracts"
            / "synapse"
            / "fixtures"
            / "capability"
            / "current_state.json"
        ).read_text(encoding="utf-8")
    )
    assert fixture["id"] == CURRENT_STATE.id
    assert fixture["version"] == CURRENT_STATE.version
    assert tuple(fixture["grain"]) == CURRENT_STATE.grain
    assert fixture["tenancy"] == CURRENT_STATE.tenancy.value
    assert fixture["freshness"] == CURRENT_STATE.freshness.value
    assert set(fixture["returns"]) == set(CURRENT_STATE.returns)
    assert tuple(fixture["produces_signals"]) == CURRENT_STATE.produces_signals
    assert fixture["gates"] == [], "the fixture must carry the empty CLAIM, not omit the key"
    assert tuple(fixture["gates"]) == CURRENT_STATE.gates


def test_current_state_produces_no_signals() -> None:
    """Verified, not pending: nothing writes the signal-history table."""
    assert CURRENT_STATE.produces_signals == ()
    assert CURRENT_STATE.tenancy is Tenancy.TENANT_SCOPED
    assert CURRENT_STATE.freshness is Freshness.LAST_WRITE


def test_current_state_declares_no_gates() -> None:
    """Verified-empty for a DIFFERENT reason than produces_signals.

    The hot table either has a row for a (tenant, store, sku) or it does not; no quantity of
    history makes the answer usable or unusable, so there is genuinely nothing to gate on.
    An empty result here is a legitimate state, not an unmet gate — which is exactly the
    distinction daily_series's non-empty tuple exists to draw.
    """
    assert CURRENT_STATE.gates == ()


def test_scope_requires_a_tenant() -> None:
    """CapabilityScope exists so a fleet read cannot happen by omitting an argument."""
    with pytest.raises(TypeError):
        CapabilityScope()  # type: ignore[call-arg]


def test_a_nullable_canonical_field_projects_as_none() -> None:
    row = _project(_validated(_row(unit_cost=None, expiry_date=None, stock_qty=None)))
    assert row.unit_cost is None
    assert row.expiry_date is None
    assert row.stock_qty is None


def test_optional_fields_carry_through_when_present() -> None:
    row = _project(
        _validated(
            _row(
                unit_cost=Decimal("54.5000"),
                expiry_date=date(2026, 9, 1),
                product_category="Dairy",
                sku_status="ACTIVE",
                last_source_event_at=datetime(2026, 7, 30, 9, 0, tzinfo=UTC),
            )
        )
    )
    assert row.unit_cost == Decimal("54.5000")
    assert row.expiry_date == date(2026, 9, 1)
    assert row.product_category == "Dairy"
    assert row.last_source_event_at == datetime(2026, 7, 30, 9, 0, tzinfo=UTC)
