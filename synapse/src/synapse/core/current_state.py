"""The ``current_state`` projection — what the capability RETURNS.

Job 3 of the resolver's three (see ``resolvers/current_state.py``): the table is named
by a sqlalchemy construct, the shape is validated by dis-canonical's full 45-field
model, and this is the narrow row a consumer actually receives.

THIS MODULE IS PURE, AND THAT IS ENFORCED. It imports nothing from dis-canonical,
dis-rls or sqlalchemy — the import-linter contracts in dis/pyproject.toml forbid all
three to ``synapse.core``. The translation FROM a canonical row lives in
``synapse.resolvers.current_state``, not here.

That split was not the first design. The projection originally carried a
``from_canonical`` classmethod, which forced ``synapse.core`` to import
``dis_canonical`` — and the moment the import-linter contract was written it had to
carve out an exception for the only import it forbade, making the contract vacuous.
A contract that permits its own single violation is worse than no contract, so the
translation moved to the layer that already knows canonical. The rule stayed intact
and the layering got better; writing the contract is what exposed it.

WHY A PROJECTION AT ALL, rather than handing back the canonical model. Two reasons,
neither of them tidiness:

- ``StoreSkuCurrentPosition`` carries DIS's write-side provenance —
  ``mapping_version_id``, ``trace_id``, ``ingest_metadata``, ``dis_channel``. Those
  are how a row got written, which is DIS's concern; leaking them into the analytics
  plane invites Synapse to reason about ingestion, which is not its job.
- It carries the three UNWRITTEN signal columns. Passing them through would hand
  every consumer three fields that are always NULL and look like missing data rather
  than absent producers. They are deliberately NOT here; a consumer that wants a
  signal asks the signal contract, which currently declares no producer.

Not a Pydantic model, on purpose: validation already happened against the canonical
model one layer up, and validating again against a narrower copy would make this file
a competing definition of the same fields.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from uuid import UUID


@dataclass(frozen=True)
class CurrentStateRow:
    """One SKU position at one store, as the analytics plane sees it.

    Grain is (tenant_id, store_id, sku_id) — declared on the capability descriptor so
    a consumer can join without guessing.
    """

    tenant_id: UUID
    store_id: UUID
    sku_id: str
    product_name: str
    product_category: str | None
    sku_status: str | None
    current_retail_price: Decimal
    unit_cost: Decimal | None
    promo_price: Decimal | None
    stock_qty: Decimal | None
    reorder_point: Decimal | None
    currency: str
    expiry_date: date | None
    # Freshness travels WITH the row, not just on the descriptor. `current_state` is a
    # LAST_WRITE capability, so a consumer's only way to reason about staleness is
    # per-row timestamps: last_source_event_at is when the source said something,
    # last_updated_at is when DIS wrote it. A row can be minutes old and describe a
    # week-old fact, and only these two together show that.
    last_source_event_at: datetime | None
    last_updated_at: datetime


__all__ = ["CurrentStateRow"]
