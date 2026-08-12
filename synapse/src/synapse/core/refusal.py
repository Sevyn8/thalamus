"""The refusal vocabulary, shared by every analysis that can decline to assess a position.

WHY THIS MODULE EXISTS. ``RefusalReason`` and ``counts_by_reason`` lived in
``core/stockout_risk.py``, which was correct while stockout_risk was the only analysis that
could refuse. dead_stock now refuses too, and importing the enum from stockout_risk would
assert a relationship between the two analyses that does not exist: neither knows about the
other, and one is not a special case of the other.

THE ALTERNATIVE WAS A SECOND ENUM AND A UNION ON ``PlanResult.refusals``, and it is worse. The
map is stored as JSONB keyed by the member's string value, so a union buys nothing at the
storage layer and costs a widened type on a shared signature plus a second place to look when
reading a stored key back. One vocabulary, one move, no behaviour change.

ONE ENUM RATHER THAN ONE PER ANALYSIS, AND THE CONSEQUENCE IS DELIBERATE. Nothing stops
stockout_risk returning ``FEED_STALE`` or dead_stock returning ``NO_POSITIVE_DEMAND``; the enum
is a vocabulary, not a per-analysis permission. What binds a reason to an analysis is the branch
that produces it, and each analysis's refusal function is a single ordered chain that a reader
can check. A per-analysis enum would encode that binding in the type system and would then have
to be widened the first time two analyses genuinely share a reason, which they already do:
``NO_STOCK_QUANTITY`` means the same thing in both.

THE KEYS ARE STORED. ``synapse.run.refusals`` is a JSONB map keyed by these values, and the
column's DDL records the rule this file has to keep: a re-run of the same slot over the same
data must produce the same bytes. So a member's VALUE is part of the stored contract. Renaming
one changes the meaning of every historical run row that carried it, silently, because nothing
migrates a JSONB key. Add members; do not rename them.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from enum import StrEnum
from typing import Protocol


class RefusalReason(StrEnum):
    """Why one position could not be assessed. A CLOSED vocabulary, never free text.

    A refusal carries two things at every site that produces one: this category, which is what a
    stored breakdown groups on, and prose, which is what a human reads. Neither replaces the
    other and both are produced at the same branch so they cannot drift.

    StrEnum so a member serialises to its own value as a JSON object key without a custom
    encoder, and so a stored breakdown reads as ``{"series_too_stale": 12}`` rather than as
    integers nobody can interpret without this file.
    """

    # ---- Shared ----
    # stock_qty IS NULL. Means the same thing to both analyses: no figure arrived. stockout_risk
    # has no numerator to divide; dead_stock cannot satisfy its own premise, which is stock on
    # hand that is not selling.
    NO_STOCK_QUANTITY = "no_stock_quantity"

    # ---- stockout_risk ----
    NO_OBSERVATIONS_IN_WINDOW = "no_observations_in_window"
    SERIES_TOO_STALE = "series_too_stale"
    TOO_FEW_OBSERVATIONS = "too_few_observations"
    NO_POSITIVE_DEMAND = "no_positive_demand"

    # ---- dead_stock ----
    # A recorded figure of zero or less. SEPARATE FROM NO_STOCK_QUANTITY on purpose even though
    # both end the same way: one says no figure arrived and the other says a figure arrived
    # saying none on hand. They differ in provenance and an operator chasing a data problem needs
    # to tell them apart, which a single merged key would prevent for ever.
    NO_STOCK_ON_HAND = "no_stock_on_hand"
    # The tenant's newest sale is older than the analysis permits. A property of the TENANT's
    # feed, not of the position, so every position in the sweep carries it together.
    FEED_STALE = "feed_stale"
    # The tenant has never sent a sale at all. Distinct from FEED_STALE because "stopped
    # sending" and "never started" need different actions, and distinct from a POSITION that
    # never sold, which is dead_stock's strongest finding rather than a refusal.
    NO_SALE_HISTORY = "no_sale_history"


class Refusable(Protocol):
    """Any finding row that can carry a refusal. Structural, so no analysis imports another.

    ``counts_by_reason`` needs exactly one attribute and this names it. A base class would have
    forced both row types into an inheritance relationship for the sake of one field, which is
    the same false relationship this module exists to avoid.

    DECLARED AS A READ-ONLY PROPERTY, NOT AS AN ATTRIBUTE, and that is a typing requirement
    rather than a style choice. A Protocol with a mutable attribute is INVARIANT, so
    ``Sequence[Refusable]`` would reject a ``Sequence[StockoutRiskRow]`` even though every row
    satisfies it, and every call site would need a cast. A read-only member is covariant, and
    read-only is also the honest description: nothing here writes the field.
    """

    @property
    def refusal_reason(self) -> RefusalReason | None: ...


def counts_by_reason(rows: Sequence[Refusable]) -> Mapping[RefusalReason, int]:
    """How many positions were refused, grouped by the closed-vocabulary category.

    IT USED TO SPLIT THE PROSE, and that was a real bug rather than a style quibble. The old
    implementation derived a bucket with ``refused_because.split(";")[0].split(":")[0]``, and
    four of the five reasons then in existence interpolate ``as_of``, an observation count or a
    series end-date BEFORE that split point, so the keys varied per position and per slot.
    Harmless while the output only reached a log line; disqualifying the moment it became a value
    stored on ``synapse.run``, where a re-run of the same slot must produce the same bytes.

    Grouped on ``refusal_reason``, whose members are fixed. Only refused rows are counted, so an
    all-assessed run yields ``{}`` rather than a map of zeros: the absence of a key means nothing
    was refused for that reason, which is exactly what "no refusals" should serialise to.

    UNSORTED HERE BY DESIGN. The caller that persists this is responsible for ordering, because
    stability of the STORED form is a persistence concern; see ``run_postgres._COMPLETE``.
    """
    counts: dict[RefusalReason, int] = {}
    for row in rows:
        if row.refusal_reason is None:
            continue
        counts[row.refusal_reason] = counts.get(row.refusal_reason, 0) + 1
    return counts


__all__ = ["Refusable", "RefusalReason", "counts_by_reason"]
