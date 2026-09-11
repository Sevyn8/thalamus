"""The read-time latest-wins collapse over canonical event tables, in ONE place.

READ THIS BEFORE AGGREGATING ANYTHING OVER A CANONICAL EVENT TABLE.

The event tables are append-only: a source correction arrives as a SECOND ROW and the
current truth is resolved at READ time by taking the latest row per dedup key. The only
uniqueness those tables carry —
``uq_ssse_redelivery (tenant_id, store_id, source_id, source_event_id, row_hash)`` —
suppresses a byte-identical REDELIVERY and deliberately leaves a CORRECTION as two
rows, to be collapsed at read time.

**So the collapse is not optional for an aggregate.** ``SUM(quantity) GROUP BY date``
over the raw table counts both halves of every correction. Consumers must not read the
event tables raw.

WHY A SHARED HELPER AND NOT INLINE SQL IN THE RESOLVER. The ordering is the entire
correctness of the thing and it is easy to get subtly wrong in a way that returns
plausible numbers — see the notes on ``_TIEBREAK_TAIL`` below. Written inline it would be
copied the day a second resolver aggregates the change-events table, and this repo already
carries a duplicated poll loop where one fix missed the other copy.

WHAT THIS MODULE DOES NOT DO: it names no table. The caller passes the table construct
and its event-time column, exactly as the streaming consumer's sink parameterises the
same two facts. That keeps the table-name containment test meaningful (each resolver
still names its own table) and makes this reusable for change events unchanged.

TWO LIMITS OF THE KEY, NOT OF THIS QUERY. Both are properties of what
``source_event_id`` can distinguish, and neither is fixable here:

1. When a source supplies no ``transaction_id``/``line_item_seq``, the consumer
   derives ``source_event_id`` as ``bronze_ref || ':' || chunk_row_index``. A correction
   delivered as a NEW bronze object therefore gets a DIFFERENT dedup key, so the original
   and the correction are two keys and BOTH survive this collapse. The consumer's own
   integration test asserts this (two surviving keys), and any capability built on this
   helper must state it rather than claim corrections collapse.
2. ``row_hash`` covers the mapping-produced payload only, so a ``tax_treatment`` or
   ``mapping_version_id`` change alone does not make a redelivery distinct upstream.

THE REAL FIX IS A PLATFORM-OWNED COLLAPSE VIEW in canonical, which every plane would
share instead of each holding an expression. That is a DIS migration, not Synapse's to
write, and this module is the SECOND copy of the expression (the sink's
``_detect_duplicates`` is the first). Recorded rather than quietly accepted.
"""

from __future__ import annotations

from typing import Final

from sqlalchemy import ColumnElement, Subquery, TableClause, select

# The dedup key, in the live column mapping. Verified against the applied schema:
# all four exist on canonical.store_sku_sale_events and canonical.store_sku_change_events
# (migration 0003), and ix_ssse_dedup_key / ix_ssce_dedup_key lead with exactly this
# prefix followed by the event-time column DESC.
DEDUP_KEY: Final[tuple[str, ...]] = ("tenant_id", "store_id", "source_id", "source_event_id")

# THE TIE-BREAK TAIL, and every part of it is load-bearing. In order after the
# event-time column:
#
#   last_updated_at DESC — write time, the second-order discriminator. It must NOT lead:
#     leading with it picks the LAST WRITTEN row rather than the latest SOURCE EVENT, so
#     a late-arriving older correction would win. Its position AFTER the event-time column
#     in the order_by built below is what prevents that, and a unit test pins the position.
#   id DESC — not optional. last_updated_at is TIMESTAMPTZ NOT NULL DEFAULT NOW(), and
#     NOW() is transaction time: two rows written in one batch share it exactly, so
#     without a final discriminator the survivor is whichever row the plan happened to
#     emit first. id is uuidv7, so DESC is deterministic and time-ordered.
_TIEBREAK_TAIL: Final[tuple[str, ...]] = ("last_updated_at", "id")

_REQUIRED_BEYOND_KEY: Final[tuple[str, ...]] = _TIEBREAK_TAIL


def collapse_latest_wins(
    events: TableClause,
    *,
    event_time_column: str,
    where: ColumnElement[bool],
) -> Subquery:
    """One surviving row per dedup key, as a subquery over ``events``.

    ``where`` is pushed INSIDE the collapse rather than applied to the result. That is not
    an optimisation detail: applied outside, the DISTINCT ON would order and de-duplicate
    every tenant's rows before the tenant filter narrowed anything, and on the
    highest-volume table in canonical that is the difference between an index range scan
    over ``ix_*_dedup_key``'s leading columns and a full sort. The caller's tenant
    predicate belongs in here.

    Selects EVERY column of ``events``. The caller aggregates or projects from the
    result; narrowing here would mean this helper had to know what each capability wants.

    Raises ``ValueError`` if ``events`` lacks a column the collapse needs. Deliberately
    loud and deliberately at statement-build time: a canonical rename that removed
    ``source_event_id`` would otherwise produce a syntactically valid query that
    collapsed on the wrong key and returned confidently wrong totals.
    """
    needed = (*DEDUP_KEY, event_time_column, *_REQUIRED_BEYOND_KEY)
    available = set(events.c.keys())
    missing = [name for name in needed if name not in available]
    if missing:
        raise ValueError(
            f"cannot build the latest-wins collapse over {events.name!r}: missing column(s) "
            f"{missing}. The dedup key is {list(DEDUP_KEY)} plus the "
            f"{event_time_column}/last_updated_at/id tie-break; if canonical moved, this "
            "must fail rather than collapse on a partial key"
        )

    key_columns = [events.c[name] for name in DEDUP_KEY]
    # DISTINCT ON expressions MUST be the leftmost ORDER BY expressions — Postgres
    # requires it, and SQLAlchemy renders exactly what it is given, so the key columns are
    # repeated here rather than assumed.
    order_by = [
        *key_columns,
        events.c[event_time_column].desc(),
        *(events.c[name].desc() for name in _TIEBREAK_TAIL),
    ]
    return select(*events.c).where(where).distinct(*key_columns).order_by(*order_by).subquery("collapsed")


__all__ = ["DEDUP_KEY", "collapse_latest_wins"]
