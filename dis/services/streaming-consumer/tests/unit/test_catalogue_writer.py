"""The catalogue (snapshot) write path (Slice 14d): the completeness branch, the
staleness stamp, and the event-path-unchanged guard.

The completeness branch is pinned to the REGISTRIES, not to today's values: each
test perturbs a projection registry and asserts the derived branch follows — so a
future hardcoding or drift fails the test. The staleness tracked set is NOT
registry-derived (Slice 50d): it is an explicit published set, pinned as such below
(a registry edit must NOT move it).
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import polars as pl
import pytest

from dis_canonical import StoreSkuChangeEvent, StoreSkuCurrentPosition, StoreSkuSaleEvent
from dis_mapping import MappingResult, SourceMapping
from dis_validation import mapping_produced_columns
from streaming_consumer.envelope import IngressReadyEvent

_TENANT = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")
_STORE = UUID("019e89f9-dbd5-7703-8221-ae6b81159900")
_TRACE = UUID("019e89f9-dbd5-7703-8221-ae6b81159911")
_BRONZE = UUID("019e9508-0000-7000-8000-00000000000b")
_RECEIVED = datetime(2026, 6, 8, 9, 0, tzinfo=UTC)


def _event() -> IngressReadyEvent:
    return IngressReadyEvent(
        schema_version=1,
        trace_id=_TRACE,
        tenant_id=_TENANT,
        store_id=_STORE,
        source_id="erp_catalogue_v1",
        template_id=UUID("019e9804-12ce-7f57-b9c0-eb3c7d0e8609"),
        bronze_ref=_BRONZE,
        gcs_uri="gs://bronze/x.csv",
        received_ts=_RECEIVED,
    )


# -- the staleness set is an EXPLICIT published set (Slice 50d) -------------------


def test_catalogue_staleness_set_is_the_explicit_published_set() -> None:
    from streaming_consumer.pipeline.mapping import (
        CATALOGUE_STALENESS_COLUMNS,
        catalogue_staleness_columns,
    )

    # Slice 50d: the four catalogue-reachable freshness columns — an explicit surface,
    # NOT the retired mapping_produced ∩ event_contendable derivation. currency,
    # product_name, sku_status, promo_identifier LEFT the set; expiry_date JOINED it.
    expected = {"current_retail_price", "unit_cost", "stock_qty", "expiry_date"}
    assert catalogue_staleness_columns() == expected
    assert CATALOGUE_STALENESS_COLUMNS == expected


def test_staleness_set_is_independent_of_the_projection_registries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Slice 50d: the tracked set is EXPLICIT, so perturbing either projection registry
    # must NOT move it — the exact opposite of the retired 14d registry-follows property.
    # This pins the decoupling (a registry edit that WOULD have added a column under the
    # old intersection changes nothing now).
    import streaming_consumer.pipeline.mapping as m

    before = m.catalogue_staleness_columns()
    extended = dict(m.CHANGE_HOT_PROJECTION)
    extended[("REGULATORY", "regulatory_flag")] = "regulatory_flag"
    monkeypatch.setattr(m, "CHANGE_HOT_PROJECTION", extended)
    monkeypatch.setattr(m, "SALE_HOT_PROJECTION", {})
    assert m.catalogue_staleness_columns() == before
    assert "regulatory_flag" not in m.catalogue_staleness_columns()


# -- guaranteed_hot_columns: the catalogue branch is the IDENTITY projection ------


def test_catalogue_guaranteed_is_identity_projection() -> None:
    from streaming_consumer.pipeline.mapping import guaranteed_hot_columns

    source = SourceMapping.model_validate(
        {
            "version": 1,
            "rename": {"a": "sku_id", "b": "product_name", "c": "stock_qty"},
            "normalize": {},
            "cast": {},
            "derive": {},
        }
    )
    # Identity: the mapping-produced targets ARE the hot columns (no registry image),
    # PLUS the enrichment-guaranteed fields (currency, tax_treatment) the lib always
    # supplies on this path (slice-5b, D95).
    assert guaranteed_hot_columns(source, StoreSkuCurrentPosition) == frozenset(
        {"sku_id", "product_name", "stock_qty", "currency", "tax_treatment"}
    )


def test_catalogue_guaranteed_follows_the_targets_not_a_hardcoded_set() -> None:
    from streaming_consumer.pipeline.mapping import guaranteed_hot_columns

    # The enrichment-guaranteed fields are always present (slice-5b, D95); the
    # mapping-driven part still follows the targets exactly.
    enrichment = frozenset({"currency", "tax_treatment"})
    one = SourceMapping.model_validate(
        {"version": 1, "rename": {"a": "sku_id"}, "normalize": {}, "cast": {}, "derive": {}}
    )
    assert guaranteed_hot_columns(one, StoreSkuCurrentPosition) == frozenset({"sku_id"}) | enrichment
    # Add a target and the guaranteed set grows by exactly it (∩ hot columns).
    two = SourceMapping.model_validate(
        {
            "version": 1,
            "rename": {"a": "sku_id", "b": "reorder_point"},
            "normalize": {},
            "cast": {},
            "derive": {},
        }
    )
    assert (
        guaranteed_hot_columns(two, StoreSkuCurrentPosition)
        == frozenset({"sku_id", "reorder_point"}) | enrichment
    )


def test_valid_snapshot_classifies_complete_and_incomplete_does_not() -> None:
    from streaming_consumer.pipeline.mapping import classify_hot_completeness

    complete = SourceMapping.model_validate(
        {
            "version": 1,
            "rename": {
                "a": "sku_id",
                "b": "product_name",
                "c": "product_category",
                "d": "current_retail_price",
                "e": "unit_cost",
                "f": "currency",
            },
            "normalize": {},
            "cast": {},
            "derive": {},
        }
    )
    assert classify_hot_completeness(complete, StoreSkuCurrentPosition) is True
    incomplete = SourceMapping.model_validate(
        {"version": 1, "rename": {"a": "sku_id"}, "normalize": {}, "cast": {}, "derive": {}}
    )
    assert classify_hot_completeness(incomplete, StoreSkuCurrentPosition) is False


def test_currency_omitted_still_complete_via_enrichment_companion_still_incomplete() -> None:
    # slice-5b (D95, criterion 4): currency LEFT the mapping-required set (the lib now
    # guarantees it), so a snapshot mapping that does NOT map currency classifies
    # COMPLETE — where pre-slice it would NOT (currency was required from the projection).
    from streaming_consumer.pipeline.mapping import classify_hot_completeness

    no_currency = SourceMapping.model_validate(
        {
            "version": 1,
            "rename": {
                "a": "sku_id",
                "b": "product_name",
                "c": "product_category",
                "d": "current_retail_price",
                "e": "unit_cost",
            },
            "normalize": {},
            "cast": {},
            "derive": {},
        }
    )
    assert classify_hot_completeness(no_currency, StoreSkuCurrentPosition) is True
    # Companion: a mapping still missing a genuinely-required projected field stays
    # INCOMPLETE. The required set narrowed by currency (16i) AND product_category +
    # unit_cost (16j, now nullable), so the demonstration omits current_retail_price —
    # which REMAINS required — rather than unit_cost (which would now classify COMPLETE).
    missing_required = SourceMapping.model_validate(
        {
            "version": 1,
            "rename": {
                "a": "sku_id",
                "b": "product_name",
                "c": "product_category",
                "e": "unit_cost",
            },
            "normalize": {},
            "cast": {},
            "derive": {},
        }
    )
    assert classify_hot_completeness(missing_required, StoreSkuCurrentPosition) is False


def test_enriched_value_is_seen_by_post_validation_gate() -> None:
    # slice-5b (D94, criterion 3): enrichment runs BEFORE post-validation, so the gate
    # SEES enriched values. A valid store currency is char(3) and can never be invalid,
    # so the gate's EXISTENCE is proven with a deliberately-invalid handed-in fact — NOT
    # a production-reachable path (documented so this is not later mistaken for dead code
    # and removed). The valid companion proves a good enriched value passes.
    from streaming_consumer.pipeline.mapping import LoadedMapping, apply_loaded_enrichment
    from streaming_consumer.pipeline.validate_post import run_post_validation

    source = SourceMapping.model_validate(
        {"version": 1, "rename": {"a": "sku_id"}, "normalize": {}, "cast": {}, "derive": {}}
    )
    loaded = LoadedMapping(
        mapping_version_id=1, source=source, target_model=StoreSkuCurrentPosition, hot_complete=False
    )
    base = MappingResult(contribution=pl.DataFrame({"sku_id": ["X"]}), source_row_indices=(0,))

    bad = apply_loaded_enrichment(
        {"currency": "TOOLONGCUR", "tax_treatment": "INCLUSIVE"}, base, tenant_id="t", trace_id="r"
    )
    assert run_post_validation(loaded, bad.contribution, tenant_id="t", trace_id="r").passed is False

    good = apply_loaded_enrichment(
        {"currency": "USD", "tax_treatment": "INCLUSIVE"}, base, tenant_id="t", trace_id="r"
    )
    assert run_post_validation(loaded, good.contribution, tenant_id="t", trace_id="r").passed is True


# -- _catalogue_groups: identity projection, natural key, staleness stamp ---------


def _result(rows: list[dict[str, object]]) -> MappingResult:
    return MappingResult(
        contribution=pl.DataFrame(rows),
        source_row_indices=tuple(range(len(rows))),
    )


def test_catalogue_groups_project_and_stamp() -> None:
    from streaming_consumer.sinks.canonical import _catalogue_groups

    result = _result(
        [
            {
                "sku_id": "SKU-1",
                "sku_variant": None,
                "sku_lot_batch": None,
                "product_name": "Widget",
                "product_category": "Hardware",
                "current_retail_price": "9.99",
                "unit_cost": "4.00",
                "currency": "EUR",
                "reorder_point": "5",  # set but NOT in the tracked set → not stamped
            }
        ]
    )
    groups = _catalogue_groups(_event(), result)
    assert len(groups) == 1
    group = groups[0]
    assert group.natural_key == ("SKU-1", None, None)
    assert group.last_source_event_at == _RECEIVED  # received_ts is the event-time
    # Natural-key columns are NOT in projected (carried as fixed params).
    assert "sku_id" not in group.projected
    # Slice 50d: attribute_staleness_map stamps only the TRACKED columns the row set,
    # with the received_ts value. This row sets price + cost (tracked) but also
    # product_name/currency (written as values, NOT tracked) and reorder_point (neither).
    import orjson

    stamp = orjson.loads(group.projected["attribute_staleness_map"])
    assert set(stamp) == {"current_retail_price", "unit_cost"}
    assert set(stamp.values()) == {_RECEIVED.isoformat()}
    assert "product_name" not in stamp  # written as a value, not a freshness-tracked field
    assert "currency" not in stamp
    assert "reorder_point" not in stamp
    assert group.projected["reorder_point"] == "5"  # still written, just not stamped
    assert group.projected["product_name"] == "Widget"  # value write intact


def test_catalogue_groups_blank_tracked_column_not_stamped() -> None:
    # Slice 50f Fix 1: the stamp trigger is NON-NULL-VALUE-PRESENT, not projected-membership. A
    # tracked column present but NULL is NOT stamped; a non-null tracked column in the same row
    # still is. The filter is `is not None`, NOT truthiness — a legitimate ZERO (0.00 price, 0 qty)
    # MUST still stamp, which truthiness would wrongly drop.
    from streaming_consumer.sinks.canonical import _catalogue_groups

    result = _result(
        [
            {
                "sku_id": "SKU-2",
                "sku_variant": None,
                "sku_lot_batch": None,
                "product_name": "Widget",
                "current_retail_price": 0.0,  # tracked, ZERO but non-null → MUST stamp
                "unit_cost": None,  # tracked, NULL → NOT stamped
                "stock_qty": 0,  # tracked, ZERO but non-null → MUST stamp
            }
        ]
    )
    import orjson

    group = _catalogue_groups(_event(), result)[0]
    stamp = orjson.loads(group.projected["attribute_staleness_map"])
    assert set(stamp) == {"current_retail_price", "stock_qty"}  # zero values stamped
    assert "unit_cost" not in stamp  # NULL tracked column not stamped
    # Fix 1 changes only the stamp keys — the NULL value column is still written.
    assert group.projected["unit_cost"] is None


# -- the event path is UNCHANGED (the load-bearing guard) -------------------------


def test_event_routing_and_completeness_unchanged() -> None:
    # A sale and a change mapping still route by column inference and classify
    # incomplete exactly as before — the catalogue path added nothing to their flow.
    from streaming_consumer.pipeline.mapping import classify_hot_completeness, route_target_model

    sale = SourceMapping.model_validate(
        {
            "version": 1,
            "rename": {"sku": "sku_id", "ts": "source_sale_timestamp", "q": "quantity"},
            "normalize": {},
            "cast": {},
            "derive": {},
        }
    )
    assert route_target_model(sale, tenant_id="t", trace_id="r") is StoreSkuSaleEvent
    assert classify_hot_completeness(sale, StoreSkuSaleEvent) is False

    change = SourceMapping.model_validate(
        {
            "version": 1,
            "rename": {"sku": "sku_id", "when": "source_event_timestamp", "v": "value_after"},
            "normalize": {},
            "cast": {},
            "derive": {},
        }
    )
    assert route_target_model(change, tenant_id="t", trace_id="r") is StoreSkuChangeEvent
    assert classify_hot_completeness(change, StoreSkuChangeEvent) is False


def test_hot_model_is_not_in_the_event_routing_universe() -> None:
    # The catalogue target is reached by template_type, NOT by adding the hot table
    # to EVENT_MODELS (route_target_model still only knows the two event models).
    from streaming_consumer.pipeline.mapping import EVENT_MODELS

    assert StoreSkuCurrentPosition not in EVENT_MODELS
    assert set(EVENT_MODELS) == {StoreSkuSaleEvent, StoreSkuChangeEvent}
    # And the hot model has its own mapping-produced set (the catalogue field universe).
    assert "stock_qty" in mapping_produced_columns(StoreSkuCurrentPosition)
