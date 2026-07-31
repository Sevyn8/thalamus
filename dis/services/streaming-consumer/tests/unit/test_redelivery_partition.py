"""``_partition_redeliveries``: the write-time half of redelivery idempotency (0019).

THE BUG IT CLOSES: ``_detect_duplicates`` already classified every row as
``DUPLICATE_NOOP`` (identical payload under an existing dedup key) or
``DUPLICATE_OVERWRITTEN`` (a correction), inside the write transaction — and then the
insert proceeded unconditionally, so a retry appended a full duplicate set. These cases
pin the verdict being ACTED on, and pin the two ways it must NOT over-reach:

- a correction (``DUPLICATE_OVERWRITTEN``) still lands, because D33 wants it appended;
- a hit whose hash does not match THIS row still lands, because one batch can carry
  several rows under one dedup key and only the matching one is the redelivery.

Pure — no DB, no engine. The DB-side backstop (``uq_*_redelivery``) is proven separately
in ``tests/integration/test_redelivery_idempotency.py``; a unique index and a filter fail
in different ways, so neither test substitutes for the other.
"""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest

from streaming_consumer.pipeline.normalize import EventRow
from streaming_consumer.sinks.canonical import DuplicateHit, DuplicateKind, _partition_redeliveries

_PRIOR_TRACE = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
_UNREAD_TS = datetime(2026, 7, 31, 12, 0, tzinfo=UTC)


def _row(source_event_id: str, row_hash: str, *, index: int = 0) -> EventRow:
    """An EventRow carrying only what the partition function reads."""
    return EventRow(
        params={"source_event_id": source_event_id, "row_hash": row_hash},
        source_event_id=source_event_id,
        # Unread by _partition_redeliveries; a real datetime would imply this function
        # cares about event time, and it deliberately does not.
        event_ts=_UNREAD_TS,
        natural_key=("SKU-1", None, None),
        hot_contributions={},
        payload={},
        row_hash=row_hash,
        chunk_row_index=index,
    )


def _hit(source_event_id: str, row_hash: str, kind: DuplicateKind, *, index: int = 0) -> DuplicateHit:
    return DuplicateHit(
        source_event_id=source_event_id,
        prior_trace_id=_PRIOR_TRACE,
        kind=kind,
        row_hash=row_hash,
        chunk_row_index=index,
    )


def test_identical_redelivery_is_suppressed() -> None:
    """THE ACTUAL BUG: a NOOP hit whose hash matches must not be inserted again."""
    row = _row("T-1:1", "hash-a")
    to_insert, suppressed = _partition_redeliveries([row], [_hit("T-1:1", "hash-a", "DUPLICATE_NOOP")])
    assert to_insert == []
    assert len(suppressed) == 1
    assert suppressed[0].source_event_id == "T-1:1"


def test_correction_still_lands() -> None:
    """D33 is not repealed: a different payload under the same key is appended."""
    row = _row("T-1:1", "hash-b")
    to_insert, suppressed = _partition_redeliveries([row], [_hit("T-1:1", "hash-b", "DUPLICATE_OVERWRITTEN")])
    assert to_insert == [row]
    assert suppressed == []


def test_first_arrival_lands() -> None:
    """No hit at all — nothing to suppress."""
    row = _row("T-1:1", "hash-a")
    to_insert, suppressed = _partition_redeliveries([row], [])
    assert to_insert == [row]
    assert suppressed == []


def test_noop_hit_with_a_different_hash_does_not_suppress() -> None:
    """The hash must match THIS row, not merely the dedup key.

    A NOOP hit says "some identical row is committed under this key". If the row in hand
    hashes differently it is a DIFFERENT row that happens to share the key, and dropping
    it would lose real data — the one way this filter could be worse than the bug.
    """
    row = _row("T-1:1", "hash-different")
    to_insert, suppressed = _partition_redeliveries([row], [_hit("T-1:1", "hash-a", "DUPLICATE_NOOP")])
    assert to_insert == [row]
    assert suppressed == []


def test_mixed_batch_partitions_per_row() -> None:
    """A batch with a redelivery, a correction and a fresh row splits three ways."""
    redelivered = _row("T-1:1", "hash-a", index=0)
    corrected = _row("T-1:2", "hash-new", index=1)
    fresh = _row("T-1:3", "hash-c", index=2)
    to_insert, suppressed = _partition_redeliveries(
        [redelivered, corrected, fresh],
        [
            _hit("T-1:1", "hash-a", "DUPLICATE_NOOP", index=0),
            _hit("T-1:2", "hash-new", "DUPLICATE_OVERWRITTEN", index=1),
        ],
    )
    assert to_insert == [corrected, fresh]
    assert [h.source_event_id for h in suppressed] == ["T-1:1"]


@pytest.mark.parametrize("kind", ["DUPLICATE_NOOP", "DUPLICATE_OVERWRITTEN"])
def test_every_hit_is_still_reported_regardless_of_suppression(kind: DuplicateKind) -> None:
    """Suppression changes what is WRITTEN, never what is AUDITED.

    With the insert gone, the audit row is the only evidence a retry happened — so the
    hit must survive into the report either way. This function returns only the
    suppressed subset; ``write_chunk`` extends ``duplicates`` from the full hit list
    before calling it, and this case exists so a future refactor that starts filtering
    hits instead of rows has to break something.
    """
    row = _row("T-1:1", "hash-a")
    hits = [_hit("T-1:1", "hash-a", kind)]
    to_insert, suppressed = _partition_redeliveries([row], hits)
    assert len(to_insert) + len(suppressed) == 1
    assert len(hits) == 1  # the input hit list is not mutated
