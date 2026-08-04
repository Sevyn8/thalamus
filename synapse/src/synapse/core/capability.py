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
- ``preconditions``: forced by the SECOND resolver. ``current_state`` answers for any
  tenant that exists; ``daily_series`` cannot answer usefully for a tenant with twelve
  days of history. That makes resolution "can this be satisfied FOR THIS TENANT, RIGHT
  NOW" rather than "does a resolver exist", and a consumer must be able to learn the
  requirement WITHOUT calling the resolver — which is only possible if it is declared
  here. See the field comment for the declaration/measurement split.

DELIBERATELY ABSENT, because two resolvers cannot justify them: cost/latency classes,
caching, substitution rules, pagination shape, and any notion of a capability
composing another. Adding them from two samples would be guessing, and this project
has a standing rule about artifacts that assert more than they know.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import ClassVar
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
class MinHistoryDays:
    """A series needs at least ``days`` distinct dates of OBSERVATIONS in scope.

    COVERAGE, NOT SPAN. A forecaster needs observations, not calendar distance. A tenant
    onboarded ninety days ago that has sold on twelve of them has a span of 90 and a
    coverage of 12, and only the 12 is a count of things a model can fit to. So ``days``
    counts DISTINCT dates CARRYING DATA. Span is the rejected alternative, named here so the
    next reader knows it was a choice rather than an implementation accident.

    MEASURED PER SERIES, not per tenant. The measurement grain is the capability's declared
    grain minus the date column, and that is enforced at registry import — see the grain rule
    in synapse/registry.py. A per-tenant count would pass trivially while saying nothing
    about whether any individual series is forecastable, which is the defect that rule exists
    to make impossible.

    A FITNESS precondition, not a computability one. A twelve-day daily series computes
    perfectly well; it is just not the thing a consumer asking for a series means. The
    resolution engine therefore REFUSES rather than returning a short series, because
    handing back twelve days to a consumer that assumed sixty is the same class of
    error the ``freshness`` enum exists to prevent — a plausible answer to a question
    nobody asked.

    ``name`` is a ClassVar, so it cannot be set per-instance and cannot drift from the
    probe that measures it (the registry pairs the two BY this name).
    """

    name: ClassVar[str] = "min_history_days"

    # STANDING IN FOR A CALLER. See the DAILY_SERIES declaration for why any value here is
    # provisional: this is an argument OF A REQUIREMENT, not a property of the capability.
    days: int

    def __post_init__(self) -> None:
        if self.days < 1:
            raise ValueError(f"min_history_days must be at least 1 day, got {self.days}")


# ONE KIND, and the alias exists so that adding a second is a VISIBLE edit here rather
# than a new string flowing through a generic (name, operator, value) triple. Such a
# triple invented from one sample is exactly the guessing this module's docstring rules
# out for cost classes and caching; the union grows when a second precondition is real.
type Precondition = MinHistoryDays


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
    # names a table, so it belongs to synapse.resolvers — the only layer allowed to (D6).
    # That is not a preference: import-linter forbids dis_rls/sqlalchemy to synapse.core,
    # so a probe placed here would fail lint.
    #
    # NO DEFAULT, deliberately, for the same reason produces_signals has none: an empty
    # tuple is a claim ("verified: this answers for any tenant that exists") and a
    # missing argument is a silence, and the two must not be the same value.
    preconditions: tuple[Precondition, ...]


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
    # not an unmet precondition.
    preconditions=(),
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
    # NON-EMPTY, and this capability is why the field exists. See MinHistoryDays for what
    # the threshold means (coverage, not span) and why an unmet precondition is a refusal
    # rather than a short answer.
    #
    # THE 60 IS STANDING IN FOR A CALLER, AND IS NOT A PROPERTY OF THIS CAPABILITY.
    # min_days is an argument OF THE REQUIREMENT, not of the data source: a dead-stock rule
    # wants 90 days of no-sales, a forecast wants 60 for seasonality, and both ask
    # daily_series for exactly the same rows. The same capability with two callers has two
    # thresholds, so pinning one here is a placeholder for the parameter that does not exist
    # yet.
    #
    # It becomes a real parameter in SLICE 2, when the analysis declaration exists and can
    # supply it — along with the policy for what to do with the per-series counts (see
    # satisfies_placeholder_policy). Until then the declaration is here because the
    # measurement and the gate have to be exercised by something, and an unexercised gate is
    # the artifact class this project keeps deleting.
    preconditions=(MinHistoryDays(days=60),),
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
    "CapabilityDescriptor",
    "CapabilityScope",
    "Freshness",
    "MinHistoryDays",
    "Precondition",
    "Tenancy",
]
