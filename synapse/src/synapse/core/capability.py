"""Capability types, EXTRACTED from building the ``current_state`` resolver.

These were not designed in advance. Every field below exists because writing
``resolvers/current_state.py`` could not be done without it, and the JSON Schema in
``contracts/synapse/capability.schema.json`` was written from this file rather than
the other way round. Where a field looks thin, that is because one resolver is a
sample of one — the honest reason, not an oversight.

WHAT BUILDING ONE RESOLVER ACTUALLY FORCED:

- ``id`` + ``version``: a consumer has to name what it is asking for, and the shape
  of an answer changes over time. SemVer, matching the C6 pack contract.
- ``grain``: the resolver's rows mean one thing per (tenant, store, sku). Without a
  declared grain a consumer cannot join two capabilities or know what a row IS, and
  every analytics mistake downstream starts there.
- ``tenancy``: the resolver had to decide, at the signature, whether scope was
  required or optional. That is not an implementation detail — it is the difference
  between a tenant read and a fleet read, so it belongs in the contract.
- ``freshness``: ``current_state`` answers "as of the last write", which is a
  materially different promise from "as of a date". A consumer that cannot tell
  these apart will average a point-in-time against a series.
- ``produces_signals``: DISCOVERED, and the discovery is the interesting part. See
  the note on it below.

DELIBERATELY ABSENT, because one resolver cannot justify them: cost/latency classes,
caching, substitution rules, pagination shape, and any notion of a capability
composing another. Adding them from one sample would be guessing, and this project
has a standing rule about artifacts that assert more than they know.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class Tenancy(StrEnum):
    """Whose data a capability may read.

    ``TENANT_SCOPED`` means the scope's tenant is required and the read cannot widen.
    ``FLEET`` would mean a deliberate cross-tenant read; no capability declares it
    today, and it is present only so that a future one must SAY so rather than
    acquire the ability by omitting a field.
    """

    TENANT_SCOPED = "tenant_scoped"
    FLEET = "fleet"


class Freshness(StrEnum):
    """What instant a capability's answer describes.

    ``LAST_WRITE`` — the value as of whenever the row was last written. No date
    parameter is meaningful; asking for "yesterday" is not answerable.
    ``AS_OF_DATE`` — a value stamped with the date it describes, so a series exists
    and a date parameter is meaningful.

    The distinction is here because ``current_state`` is the first and the
    signal-history table is the second, and conflating them would let a consumer
    average a point-in-time reading against a time series without any layer
    objecting.
    """

    LAST_WRITE = "last_write"
    AS_OF_DATE = "as_of_date"


@dataclass(frozen=True)
class CapabilityScope:
    """The tenancy a capability call runs under.

    Frozen, and ``tenant_id`` is REQUIRED with no default. That is the whole point of
    the type: a resolver signature that accepted ``tenant_id: UUID | None = None``
    would make a fleet-wide read the easiest thing to write by accident. A future
    FLEET capability gets an explicit separate constructor rather than a ``None``
    that means "everything".
    """

    tenant_id: UUID


@dataclass(frozen=True)
class CapabilityDescriptor:
    """What a capability declares about itself. Mirrors capability.schema.json.

    Kept as a plain frozen dataclass rather than a Pydantic model: the SCHEMA is the
    contract and the conformance harness is what enforces it, so a second validating
    implementation here would be a second source of truth for the same rules.
    """

    id: str
    version: str
    grain: tuple[str, ...]
    tenancy: Tenancy
    freshness: Freshness
    returns: tuple[str, ...]
    # DISCOVERED, and it is the reason signals are a separate contract (D5).
    #
    # `current_state` reads the canonical hot table, which HAS the three signal
    # columns — velocity_7day, stock_age_days, unit_cost_trend_30day. It produces
    # none of them, because NOTHING WRITES THEM: there is no daily-compute
    # job, no Cloud Run job, and Cloud Scheduler has never been enabled on the
    # project. The columns are real and always NULL.
    #
    # So a capability that reads a signal column is not a producer of that signal,
    # and the descriptor has to be able to say so. An empty tuple here is a
    # first-class, verified state — not a placeholder waiting to be filled in.
    produces_signals: tuple[str, ...]


CURRENT_STATE = CapabilityDescriptor(
    id="current_state",
    version="0.1.0",
    grain=("tenant_id", "store_id", "sku_id"),
    tenancy=Tenancy.TENANT_SCOPED,
    freshness=Freshness.LAST_WRITE,
    returns=(
        "tenant_id",
        "store_id",
        "sku_id",
        "product_name",
        "product_category",
        "sku_status",
        "current_retail_price",
        "unit_cost",
        "promo_price",
        "stock_qty",
        "reorder_point",
        "currency",
        "expiry_date",
        "last_source_event_at",
        "last_updated_at",
    ),
    # Verified empty, not yet-to-be-filled. See the field comment above.
    produces_signals=(),
)

__all__ = [
    "CURRENT_STATE",
    "CapabilityDescriptor",
    "CapabilityScope",
    "Freshness",
    "Tenancy",
]
