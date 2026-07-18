"""Spine provisioning: register the api source + the ACTIVE snapshot template (D88).

Direct-DB provisioning for the backend spine (steps 1-2). It is NOT the ver2 path (steps
6-7 exercise the real POST /sources + POST /mapping-templates). Create-as-ACTIVE (D88): the
template is written ACTIVE directly, no staged-to-activate step. Idempotent: an existing
source or ACTIVE snapshot template for the (tenant, source) is reused, so re-provisioning is
a no-op and returns the same template_id.

RLS: config.sources and config.source_mappings are RLS ON (two-GUC, D91); the seeding role
is NOBYPASSRLS, so the inserts set the transaction-local app.tenant_id / app.user_type GUCs
first (mirrors dis_testing.seed). The template's mapping_rules is derived from the
connector's own SNAPSHOT_HEADER so it cannot drift from the CSV the connector writes: an
identity rename of each snapshot column plus a decimal normalize+cast on the numeric ones.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import create_engine, text

from dis_core.ids import new_uuid7
from thalamus_square.mapping import SNAPSHOT_HEADER

# The snapshot columns that arrive as decimal strings and need a parse+cast (the rest are
# plain text). Precision/scale match canonical.store_sku_current_position.
_DECIMAL_CASTS: dict[str, tuple[int, int]] = {
    "current_retail_price": (12, 4),
    "stock_qty": (14, 3),
}


@dataclass(frozen=True)
class ProvisionResult:
    """What the spine provisioned: the source slug and the ACTIVE template id."""

    source_id: str
    template_id: UUID


def snapshot_mapping_rules() -> dict[str, object]:
    """A valid SourceMapping document for the snapshot template, derived from SNAPSHOT_HEADER.

    EQUIVALENT BY CONSTRUCTION to what the BFF ``POST /mapping-templates`` produces from the
    same per-column intent (identity ``src_key -> dest_key``, decimal separator on the numeric
    columns): ``translate_columns_to_mapping_rules`` emits a ``cast`` for EVERY known column, so
    this mirrors it exactly - a decimal cast (precision/scale from the canonical model) on the
    numeric columns, and a type-only string cast (precision/scale null) on the text columns.
    The `tests/unit/test_provisioning_equivalence.py` drift guard asserts this equality.

    currency is renamed through but its value is enrichment-owned (the store's), so the
    streaming consumer overwrites it (D95); tax_treatment is enrichment-only and not mapped.
    """
    rename = {column: column for column in SNAPSHOT_HEADER}
    normalize = {
        column: [{"op": "parse_decimal", "args": {"decimal_separator": ".", "thousands_separator": None}}]
        for column in _DECIMAL_CASTS
    }
    cast: dict[str, dict[str, object]] = {}
    for column in SNAPSHOT_HEADER:
        if column in _DECIMAL_CASTS:
            precision, scale = _DECIMAL_CASTS[column]
            cast[column] = {"type": "decimal", "precision": precision, "scale": scale}
        else:
            cast[column] = {"type": "string", "precision": None, "scale": None}
    return {"version": 1, "rename": rename, "normalize": normalize, "cast": cast, "derive": {}}


def provision(
    *,
    url: str,
    tenant_id: UUID,
    store_code: str,
    source_id: str,
    display_name: str = "Square POS (sandbox)",
    template_name: str = "square snapshot",
) -> ProvisionResult:
    """Provision the api source + ACTIVE snapshot template for (tenant, source). Idempotent."""
    engine = create_engine(url)
    try:
        with engine.begin() as conn:
            conn.execute(text("SELECT set_config('app.user_type', 'TENANT', true)"))
            conn.execute(text("SELECT set_config('app.tenant_id', :t, true)"), {"t": str(tenant_id)})

            conn.execute(
                text(
                    "INSERT INTO config.sources "
                    "(tenant_id, source_id, display_name, channel, store_id, status) "
                    "VALUES (:t, :s, :d, 'api', :store, 'active') "
                    "ON CONFLICT (tenant_id, source_id) DO NOTHING"
                ),
                {"t": str(tenant_id), "s": source_id, "d": display_name, "store": store_code},
            )

            existing = conn.execute(
                text(
                    "SELECT template_id FROM config.source_mappings "
                    "WHERE tenant_id = :t AND source_id = :s AND status = 'ACTIVE' "
                    "  AND template_type = 'snapshot' LIMIT 1"
                ),
                {"t": str(tenant_id), "s": source_id},
            ).scalar()
            if existing is not None:
                return ProvisionResult(source_id=source_id, template_id=UUID(str(existing)))

            template_id = new_uuid7()
            conn.execute(
                text(
                    "INSERT INTO config.source_mappings "
                    "(tenant_id, source_id, template_id, template_name, template_type, status, "
                    " mapping_rules, activated_at) "
                    "VALUES (:t, :s, CAST(:tpl AS uuid), :name, 'snapshot', 'ACTIVE', "
                    " CAST(:rules AS JSONB), NOW())"
                ),
                {
                    "t": str(tenant_id),
                    "s": source_id,
                    "tpl": str(template_id),
                    "name": template_name,
                    "rules": json.dumps(snapshot_mapping_rules()),
                },
            )
            return ProvisionResult(source_id=source_id, template_id=template_id)
    finally:
        engine.dispose()
