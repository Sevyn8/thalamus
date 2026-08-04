"""The ``last_sale_at`` projection — when each position last actually SOLD.

PURE, like its siblings: import-linter forbids dis_canonical, dis_rls and sqlalchemy to
``synapse.core``, so the query and the canonical row shapes stay in
``synapse.resolvers.last_sale_at``.

WHY THIS IS ITS OWN CAPABILITY AND NOT A FIELD ON ANOTHER. "When did this last move" is a
different question from "what moved each day", and folding it into ``daily_series`` would make
that capability answer two questions with one grain — the first step to a god-object. The split
is also what makes dead stock expressible at all: ``current_state`` is the universe of
positions, this is the subset that has ever sold, and an absence is the difference between
them. Both declare grain ``(tenant_id, store_id, sku_id)`` and the registry checks they match.

ONE ROW PER POSITION THAT HAS EVER SOLD. A position that has never sold has NO ROW — that is
not a gap to be filled, it is the strongest dead-stock signal there is, and the consumer reads
it as a missing row against ``current_state``'s universe.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from uuid import UUID


@dataclass(frozen=True)
class LastSaleAtRow:
    """The most recent SALE date for one SKU at one store.

    Grain is (tenant_id, store_id, sku_id) — declared on the capability descriptor and matching
    this dataclass field-for-field (a unit test pins the two together).
    """

    tenant_id: UUID
    store_id: UUID
    sku_id: str
    # A UTC DATE, because canonical derives event_date from source_sale_timestamp at UTC under
    # a CHECK constraint and that is the honest grain of the underlying fact. Never NULL: a row
    # exists only because a sale exists, so there is always a date. "Never sold" is the absence
    # of the row, not a NULL in it — the distinction matters because a NULL invites
    # COALESCE and a missing row does not.
    #
    # SALE ONLY. RETURN and VOID are excluded; see the resolver for why a return is not
    # movement.
    last_sale_date: date


__all__ = ["LastSaleAtRow"]
