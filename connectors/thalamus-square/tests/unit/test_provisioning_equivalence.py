"""Equivalence drift guard: the spine's direct-DB snapshot mapping rules MUST equal what the
BFF ``POST /mapping-templates`` stores for the same per-column intent.

The UI path posts ``columns[]`` (src_key -> dest_key + a decimal separator on the numeric
columns); the BFF runs ``translate_columns_to_mapping_rules`` then
``validate_mapping_rules_for_type`` and stores ``model_dump(mode="json")``. The spine writes
``provisioning.snapshot_mapping_rules()`` directly. This test asserts the two are identical, so a
future change to the BFF translator (e.g. a new cast field) fails HERE and forces
``provisioning.py`` to be reconciled - the UI and the proven pipeline never diverge silently.

Offline + pure (no DB): translate/validate are pure functions. The dis_ui_server imports carry
``type: ignore[import-untyped]`` (that package ships no py.typed) and are test-only, so the
import-linter contract on the ``thalamus_square`` package is unaffected.
"""

from __future__ import annotations

from dis_ui_server.mapping_translation import (  # type: ignore[import-untyped]
    translate_columns_to_mapping_rules,
)
from dis_ui_server.mapping_validation import (  # type: ignore[import-untyped]
    validate_mapping_rules_for_type,
)
from dis_ui_server.schemas.mapping_templates import (  # type: ignore[import-untyped]
    MappingColumn,
    MappingTemplateCreate,
)
from thalamus_square.mapping import SNAPSHOT_HEADER
from thalamus_square.provisioning import snapshot_mapping_rules

_TENANT = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"
_DECIMAL_COLUMNS = {"current_retail_price", "stock_qty"}


def _snapshot_columns() -> list[MappingColumn]:
    """The per-column create intent the onboarding screen posts: identity src->dest for each
    SNAPSHOT_HEADER column, with a decimal separator on the numeric ones."""
    columns: list[MappingColumn] = []
    for key in SNAPSHOT_HEADER:
        if key in _DECIMAL_COLUMNS:
            columns.append(
                MappingColumn(
                    src_key=key, dest_key=key, src_decimal_separator=".", src_thousand_separator=None
                )
            )
        else:
            columns.append(MappingColumn(src_key=key, dest_key=key))
    return columns


def test_spine_rules_equal_the_bff_translated_rules() -> None:
    body = MappingTemplateCreate(
        source_id="square_pos_v2",
        template_name="square snapshot",
        template_type="snapshot",
        columns=_snapshot_columns(),
    )
    translated = translate_columns_to_mapping_rules(body, tenant_id=_TENANT)
    stored_by_bff = validate_mapping_rules_for_type(
        translated, template_type="snapshot", tenant_id=_TENANT
    ).model_dump(mode="json")
    assert snapshot_mapping_rules() == stored_by_bff
