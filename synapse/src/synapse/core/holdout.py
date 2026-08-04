"""Holdout assignment. Deterministic, stable, and computed rather than stored.

WHY THIS EXISTS BEFORE ANYTHING CONSUMES AN ACTION. A counterfactual cannot be constructed
retrospectively. If the first thousand actions are recorded without an arm, there is no way to
learn later what would have happened without them — the comparison group does not exist and
cannot be invented. So assignment is present from the first action ever produced, and there is
no default that means "not assigned".

STABLE WITHOUT PERSISTENCE, which is the property that makes a table unnecessary here. The arm
is a pure function of (salt, subject): the same SKU in the same store lands in the same arm on
every run, in every process, for as long as the salt is unchanged. That is strictly better than
a stored assignment, which can be lost, edited, or silently re-seeded — a derived arm is
re-derivable years later by anyone auditing the study.

===============================================================================================
DO NOT USE ``hash()`` HERE. NOT AS A SHORTCUT, NOT "JUST FOR NOW".
===============================================================================================

Python randomises string hashing per process via PYTHONHASHSEED. ``hash("SKU-1") % 100`` returns
a DIFFERENT bucket in every interpreter run, so every subject would be reassigned on every run:
a SKU treated on Monday is held out on Tuesday and treated again on Wednesday. Nothing raises,
no test that runs inside one process notices, and the resulting comparison is not a weak signal
— it is noise with a treatment label on it. Six months of data would be worthless and the
failure would be invisible until someone tried to analyse it.

sha256 is used because it is stable across processes, across interpreter versions, and across
machines, and because a well-distributed digest is what makes the bucket split unbiased.
``test_assignment_is_stable_across_processes`` runs the assignment in a SEPARATE interpreter
and compares — it fails if anyone swaps this back.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from enum import StrEnum

# How many buckets the digest is reduced to. 100 so that ``holdout_percent`` reads as a
# percentage and needs no conversion; a reader checking the arithmetic should not have to hold a
# scaling factor in their head.
_BUCKETS = 100

# Bytes of the digest folded into the bucket. Eight gives a 64-bit integer, whose modulo bias
# against 100 buckets is around 1 in 10^17 — immeasurably below any effect this could be used to
# detect, and stated so nobody has to wonder whether it was considered.
_DIGEST_BYTES = 8


class Arm(StrEnum):
    """Which side of the experiment a subject is on. Two values, no third.

    There is deliberately no ``UNASSIGNED``. An action without an arm is an action that cannot
    be analysed, and a value meaning "we did not decide" would let one exist — so the type does
    not offer the option and ``Action.arm`` has no default.
    """

    TREATMENT = "treatment"
    HOLDOUT = "holdout"


@dataclass(frozen=True)
class Holdout:
    """The experiment design an analysis is run under. Declared, not passed per call.

    ON THE DECLARATION RATHER THAN SUPPLIED BY THE CALLER, and this is the opposite of the
    ``MinHistoryDays`` decision on purpose. A threshold moved to the demand side because two
    callers legitimately want different numbers for the same capability. A holdout design does
    NOT work that way: changing the unit, the fraction or the salt INVALIDATES the comparison,
    and a caller passing a different fraction per run produces an unanalysable mixture of
    designs. The declaration is the versioned thing, so the design lives on it and a change to
    it is a version bump — which is exactly what a change of experiment should be.

    ``unit`` IS THE ASSIGNMENT GRAIN, and must be a subset of the analysis's grain (checked at
    registry import). For ``dead_stock`` it is the full grain — per (tenant, store, sku).

    WHY PER-SKU AND NOT PER-STORE for the first tenant. Per-store is the cleaner comparison in
    general and is unusable here: this tenant has TWO stores. Two units cannot be randomised,
    any difference measured is a store difference (footfall, mix, staffing) rather than a
    treatment difference, and half the customer's estate would get no service at all.

    THE COST OF PER-SKU, NAMED. It leaks under cross-SKU substitution: marking down a dead SKU
    can move a held-out neighbour, which contaminates the control. That biases the measured
    effect TOWARDS zero — it under-measures rather than over-measures, which is the safe
    direction for a claim about one's own product.

    ``salt`` IS EXPLICIT, NOT DERIVED from the declaration id and version. Deriving it would
    force a reshuffle on every version bump, including bumps that have nothing to do with the
    experiment (a new emitted field, a corrected docstring). Explicit means a version bump
    CHOOSES whether to reshuffle, which is a decision someone should make deliberately.
    """

    unit: tuple[str, ...]
    holdout_percent: int
    salt: str
    # SAME CONSTRUCTOR DISCIPLINE AS ``Threshold``, for the same reason: a fraction with no
    # stated derivation is indistinguishable from one somebody guessed, and a comment cannot be
    # enforced.
    fitted: bool
    stands_in_for: str | None

    def __post_init__(self) -> None:
        if not self.unit:
            raise ValueError("a holdout with no assignment unit cannot assign anything")
        if not 1 <= self.holdout_percent <= 99:
            raise ValueError(
                f"holdout_percent must be 1..99, got {self.holdout_percent}. 0 is not a holdout "
                "and 100 treats nobody; neither is an experiment, and both are more likely to "
                "be a mistake than an intention"
            )
        if not self.salt:
            raise ValueError(
                "a holdout needs an explicit salt; an empty one makes assignment depend on the "
                "subject alone, so two analyses over the same SKUs would assign them identically"
            )
        if not self.fitted and not self.stands_in_for:
            raise ValueError(
                "an unfitted holdout_percent must name what it stands in for. A fraction with "
                "no stated derivation is indistinguishable from a number someone guessed"
            )
        if self.fitted and self.stands_in_for:
            raise ValueError("a fitted holdout_percent stands in for nothing; remove stands_in_for")


def assign(holdout: Holdout, subject: tuple[str, ...]) -> Arm:
    """Which arm this subject is in. Pure, deterministic, and stable across processes.

    ``subject`` is the values of ``holdout.unit``, in that order — the caller is responsible for
    the correspondence, and the registry checks that ``unit`` is a subset of the analysis grain
    so the values exist to supply.

    THE SEPARATOR MATTERS. Values are joined with a character that cannot appear in a UUID or a
    canonical ``sku_id``, so ("ab", "c") and ("a", "bc") cannot collide into the same key. Without
    it two distinct subjects could share an arm assignment by accident — rare, silent, and exactly
    the kind of thing that is never found.

    Read the module docstring before changing the digest. Using ``hash()`` here would reshuffle
    every arm on every process start, silently.
    """
    if len(subject) != len(holdout.unit):
        raise ValueError(
            f"holdout unit is {holdout.unit} ({len(holdout.unit)} columns) but the subject has "
            f"{len(subject)} values; assignment would be computed over the wrong key"
        )
    key = "\x1f".join((holdout.salt, *subject))
    digest = hashlib.sha256(key.encode("utf-8")).digest()
    bucket = int.from_bytes(digest[:_DIGEST_BYTES], "big") % _BUCKETS
    return Arm.HOLDOUT if bucket < holdout.holdout_percent else Arm.TREATMENT


__all__ = ["Arm", "Holdout", "assign"]
