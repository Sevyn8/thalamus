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
- ``gates``: forced by the SECOND resolver, and INVERTED by the first analysis. See below.

WHAT COMPOSITION DID TO THIS CONTRACT: the contract was extracted from ONE resolver
(``current_state``) and survived an analysis composing TWO capabilities with seven of
eight fields unchanged — ``id``, ``version``, ``grain``, ``tenancy``, ``freshness``,
``returns`` and ``produces_signals`` needed no edit to express a two-capability analysis.

``grain`` WAS VINDICATED. It is what makes the join between two capabilities CHECKABLE:
``dead_stock`` declares grain ``(tenant_id, store_id, sku_id)`` and requires two
capabilities whose grains must contain it, which ``_check_declarations`` enforces at
import. A field extracted because "a consumer cannot join two capabilities without it"
turned out to be exactly right the first time two were joined.

``preconditions`` DID NOT SURVIVE, and could not have. It held a VALUE —
``MinHistoryDays(days=60)`` — on the SUPPLY side. That works while there is one caller
and breaks the moment there are two: dead stock wants 90 days of no-sales, a forecast
wants 60 for seasonality, and both ask the same capability for the same rows. A threshold
is an argument OF A REQUIREMENT, so it moved to the demand side
(``synapse.core.analysis``). What remains here is ``gates``: the KINDS this capability can
be measured on, which is a property of the capability because it is a property of whether
a probe exists at the right grain.

DELIBERATELY STILL ABSENT: cost/latency classes, caching, substitution rules, pagination
shape, and any notion of a capability composing another (composition lives in the ANALYSIS,
which is the layer that has a reason to compose). Adding them from three samples would
still be guessing.
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


class GateKind(StrEnum):
    """A KIND of precondition a capability can be measured on. No value, on purpose.

    A bound threshold on the supply side is wrong the moment two callers want different
    numbers, so the capability declares only what it CAN be gated on, and the caller
    supplies the number (``synapse.core.analysis``).

    A capability may declare a gate ONLY if a probe exists for it at the right grain: the
    registry enforces ``set(gates) == set(probes)`` and the grain rule per probe, both at
    import. So this is not a wish list — every value here is a measurement that exists.

    A StrEnum rather than plain strings so the probe mapping is keyed by something typed,
    and so ``match`` over it with ``assert_never`` forces a visible edit when a second kind
    arrives.
    """

    MIN_HISTORY_DAYS = "min_history_days"


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
    # DISCOVERED, and it is the reason signals are a separate contract.
    #
    # `current_state` reads the canonical hot table, which HAS the three signal
    # columns — velocity_7day, stock_age_days, unit_cost_trend_30day. It produces
    # none of them, because NOTHING WRITES THEM. Verified by grep across services, libs,
    # connectors and migrations: no writer of any kind exists for these three columns. The
    # columns are real and always NULL.
    #
    # Synapse's orchestrator IS a scheduled Cloud Run job, but it writes synapse.actions and
    # synapse.run and touches no canonical column, so the claim rests on the absence of a
    # writer rather than on the absence of a scheduler.
    #
    # So a capability that reads a signal column is not a producer of that signal,
    # and the descriptor has to be able to say so. An empty tuple here is a
    # first-class, verified state — not a placeholder waiting to be filled in.
    produces_signals: tuple[str, ...]
    # DECLARED HERE, MEASURED IN synapse.resolvers, and the split is the design.
    #
    # The declaration is pure data — a threshold, no SQL. It lives on the descriptor
    # because the descriptor is the only thing a consumer reads WITHOUT calling: if the
    # requirement lived on the resolver, an operator console could only learn "this
    # needs 60 days" by attempting a read, and telling "no resolver exists" apart from
    # "the resolver exists and this tenant is 48 days short" would require running the
    # resolver body to find out.
    #
    # The MEASUREMENT is a per-tenant database read (COUNT(DISTINCT event_date)), which
    # names a table, so it belongs to synapse.resolvers — the only layer allowed to.
    # That is not a preference: import-linter forbids dis_rls/sqlalchemy to synapse.core,
    # so a probe placed here would fail lint.
    #
    # NO DEFAULT, deliberately, for the same reason produces_signals has none: an empty
    # tuple is a claim ("verified: nothing about this capability is gateable") and a missing
    # argument is a silence, and the two must not be the same value.
    #
    # KINDS, NOT VALUES — see GateKind for why the value moved to the demand side. A caller
    # must bind every kind listed here: `resolve()` refuses a call whose supplied gate kinds
    # do not equal this tuple exactly, because a declared gate nobody binds is a gate that
    # never runs, and a gate that never runs is decorative.
    gates: tuple[GateKind, ...]


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
    # Verified empty too, and for a different reason than daily_series's non-empty tuple:
    # current_state reads the hot table, which either has a row for a (tenant, store,
    # sku) or does not. There is no quantity of history that makes the answer usable or
    # unusable, so there is nothing to require. An empty result is a legitimate state,
    # not an unmet gate.
    gates=(),
)


DAILY_SERIES = CapabilityDescriptor(
    id="daily_series",
    version="0.1.0",
    # FOUR columns, and event_date is the one that makes this a series rather than a
    # reading. It is the SURVIVING row's event_date — a correction that moves a sale to
    # another date moves the whole line, which is the behaviour a series needs.
    grain=("tenant_id", "store_id", "sku_id", "event_date"),
    tenancy=Tenancy.TENANT_SCOPED,
    # THE FIRST LIVE USE OF AS_OF_DATE. Until now the value was declared and unused —
    # present so the LAST_WRITE/AS_OF_DATE distinction existed before anything needed
    # it. This is what needed it: averaging current_state's point-in-time stock against
    # a daily series is the mistake the enum was added to make impossible to write by
    # accident.
    freshness=Freshness.AS_OF_DATE,
    returns=(
        "tenant_id",
        "store_id",
        "sku_id",
        "event_date",
        # SIGNED. RETURN and VOID rows carry their own dedup key and a NEGATIVE quantity
        # (ck_ssse_return_void_quantity_sign), so they are summed IN, never deduped away.
        # Calling this "sales" would be wrong; it is the net movement for the UTC day.
        "net_quantity",
        # One count per event_subtype in canonical's CHECK vocabulary. Exhaustive
        # BECAUSE that CHECK is, and a unit test pins the three names to
        # dis_canonical.shared.SaleEventSubtype so widening the vocabulary fails
        # loudly instead of quietly dropping a subtype out of the counts.
        "sale_line_count",
        "return_line_count",
        "void_line_count",
    ),
    # Same verified-empty state as current_state, same reason: nothing writes the
    # signal-history table, so no capability produces a signal today.
    produces_signals=(),
    # DELIBERATELY NO NUMBER HERE. This says only that daily_series CAN be gated on history
    # coverage — a probe exists for it, at the grain the registry checks. What "enough" is,
    # and how a per-series measurement reduces to a verdict, are the CALLER's to state: see
    # synapse.core.analysis.MinHistoryDays, which carries both the threshold and the
    # SeriesPolicy.
    gates=(GateKind.MIN_HISTORY_DAYS,),
)


LAST_SALE_AT = CapabilityDescriptor(
    id="last_sale_at",
    version="0.1.0",
    # SAME GRAIN AS current_state, exactly, and that is what makes dead_stock expressible:
    # current_state is the UNIVERSE (one row per position that exists), this is the
    # PRESENCES (one row per position that has ever sold), and an absence is the difference.
    # The two grains matching is checked at import, not hoped for.
    grain=("tenant_id", "store_id", "sku_id"),
    tenancy=Tenancy.TENANT_SCOPED,
    # LAST_WRITE, not AS_OF_DATE, and the distinction is exactly what the enum is for: the
    # VALUE here is a date, but no date PARAMETER is meaningful. "When did this last sell as
    # of 3 May" is not a question this answers — it answers as of the latest data held.
    freshness=Freshness.LAST_WRITE,
    # FOUR FIELDS: the grain plus one fact. Deliberately not more. The timestamp behind
    # last_sale_date, and any count of how many days a series has sold on, are both free in
    # the same aggregate — which is not a reason to return them. A capability that accretes
    # every cheap adjacent fact becomes the god-object this one was split out to avoid, and a
    # consumer that needs another field gets a version bump, which is a conversation.
    returns=("tenant_id", "store_id", "sku_id", "last_sale_date"),
    produces_signals=(),
    # NO GATES, verified rather than unfilled. "When did this last sell" is answerable from
    # ONE observation — there is no quantity of history that makes the answer more or less
    # usable, which is the same reason current_state has none. A SKU with a single sale two
    # years ago has a perfectly good last_sale_date, and for dead stock that is the most
    # interesting row in the table.
    gates=(),
)


# WHAT IS NOT HERE, and why it is not a descriptor.
#
# `lead_time_distribution` has NO descriptor and NO registry entry. The reason is
# recorded in synapse/registry.py's _DECLINED mapping as a plain string, carrying no
# grain, no returns and no freshness — because a registered capability declaring a row
# shape nobody has ever produced is precisely the artifact class this project keeps
# having to unpick. Absence plus a recorded reason distinguishes "known impossible"
# from "typo" without inventing a contract for rows that cannot exist.
#
# MONEY IS NOT IN daily_series 0.1.0, also deliberately. `tax_treatment` is per-row
# INCLUSIVE/EXCLUSIVE denormalized from the store, so SUM(quantity * unit_sale_price)
# across a tenant adds tax-inclusive to tax-exclusive amounts with nothing declaring a
# normalization. Quantity is unambiguous; money needs a decision first.
#
# UTC DAYS, not local business days. event_date is CHECK-derived from
# source_sale_timestamp at UTC. A store-local series needs the store timezone from
# identity_mirror.stores, which is outside the tables Synapse reaches today — a
# separate capability, not a parameter on this one.

__all__ = [
    "CURRENT_STATE",
    "DAILY_SERIES",
    "LAST_SALE_AT",
    "CapabilityDescriptor",
    "CapabilityScope",
    "Freshness",
    "GateKind",
    "Tenancy",
]
