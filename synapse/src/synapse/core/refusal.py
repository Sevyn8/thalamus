"""The closed vocabulary for "this position could not be assessed". Shared by every analysis.

WHY IT LIVES HERE RATHER THAN IN AN ANALYSIS. It was defined inside ``stockout_risk`` when
stockout_risk was the only analysis that could refuse. ``overstock_cash_locked`` computes the
SAME days-of-cover arithmetic read from the other tail, so it hits the same four inability
cases for the same reasons — and importing a sibling analysis to get them would make one
analysis depend on another's internals for a vocabulary neither owns.

THE VOCABULARY IS CLOSED BECAUSE THE COUNTS ARE STORED. ``synapse.run.refusals`` is a
{reason: count} map, and a key that varies per run cannot be grouped, compared, or trusted
across slots — which is exactly the defect the first ``counts_by_reason`` had when it derived
its buckets by splitting prose that interpolated dates and counts.

ADDING A MEMBER IS A CONTRACT CHANGE, not a constant edit: it widens what the stored map can
contain and every consumer that renders a label has to learn it.

TODO (gate 1, M1): ``counts_by_reason`` is currently duplicated per analysis. Generalise it
into this module at M3, when three samples exist — deferred deliberately rather than guessed
from one.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["RefusalReason"]


class RefusalReason(StrEnum):
    """The CLOSED set of reasons a position cannot be assessed. One member per refusal branch.

    WHY A VOCABULARY NOW, WHEN THE PROSE WAS ENOUGH BEFORE. The prose was enough while the only
    consumer was a human reading a log line. It stops being enough the moment a COUNT of refusals
    is stored on ``synapse.run``, because a stored breakdown needs keys that are stable across
    runs, and these reasons are not: four of the five interpolate ``as_of``, an observation count
    or a date into their leading clause. ``counts_by_reason`` used to derive its buckets by
    splitting that prose at the first colon or semicolon, which meant a re-run of the SAME SLOT
    could produce different keys — the exact thing the run row must not do.

    DERIVED FROM THE BRANCHES, NOT INVENTED. Each member below is one arm of ``_refusal`` and
    there are no others; the pairing is asserted in the unit suite so a new branch cannot ship
    without a member.

    THE PROSE SURVIVES ALONGSIDE IT. ``refused_because`` still carries the per-series specifics —
    which date, how many observations, how stale — because that is what makes a refusal
    actionable for whoever reads one row. The enum is the groupable category; the prose is the
    evidence. Neither replaces the other.

    StrEnum so a member serialises to its own value as a JSON object key without a custom
    encoder, and so a stored breakdown reads as ``{"series_too_stale": 12}`` rather than as
    integers nobody can interpret without this file.
    """

    NO_STOCK_QUANTITY = "no_stock_quantity"
    NO_OBSERVATIONS_IN_WINDOW = "no_observations_in_window"
    SERIES_TOO_STALE = "series_too_stale"
    TOO_FEW_OBSERVATIONS = "too_few_observations"
    NO_POSITIVE_DEMAND = "no_positive_demand"
