"""What an ACTION is. Pure types; no DB, no SQL, no delivery.

dead_stock emits ``is_dead_stock`` and ``days_since_last_sale``. That is a FINDING. An action is
what somebody does about it, and it needs four things a finding does not have: a verb, a target,
a value at stake, and an expiry.

TWO PROPERTIES CANNOT BE RETROFITTED AT ANY PRICE, which is the whole reason this contract comes
before anything that consumes it:

- PROVENANCE. Which declaration version, which capability versions, which thresholds, which
  as_of. Six months from now an attribution study that cannot say which system produced an
  action is comparing different systems and concluding nothing.
- THE HOLDOUT ARM. See ``synapse.core.holdout``: a counterfactual cannot be built backwards.

Everything else here can be added later. These two cannot, so they are required fields with no
defaults and the constructors refuse anything less.

APPEND-ONLY IS A PROPERTY OF THE SHAPE AND OF THE TABLE. ``ActionEvent`` is frozen, there is no
update or delete anywhere in this module or in ``synapse.core.action_log``, and a CORRECTION IS
A NEW EVENT naming the one it supersedes — the canonical event tables' append-only discipline
applied one layer up. The database says the same thing twice more: ``synapse_writer`` holds
INSERT and nothing else, and a BEFORE UPDATE OR DELETE trigger raises for every role including
the table owner.

ANALYTICS MUST READ ``synapse.actions_analytical``, NOT ``synapse.actions``. The table retains
thirteen immortal test-fixture rows written before the suite was isolated — it is append-only, so
deletion is impossible by design — and they are real-looking enough to train a model on fiction
without anyone noticing. The view excludes every tenant in ``synapse.quarantined_tenants``, whose
``note`` column carries the provenance of each entry and the boundary of what is excluded (actions
only; a quarantined tenant's runs and freshness signals are genuine). Migration 0007.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from synapse.core.holdout import Arm


class Verb(StrEnum):
    """What the action asks somebody to do. ONE value, and the restraint is the point.

    ``REVIEW`` — put this in front of a human who can decide.

    NOT ``MARK_DOWN``. Choosing a markdown needs price elasticity, a margin floor, and the
    supplier's return terms. None of the three exists anywhere in canonical, and inventing a
    percentage would be the first number in this platform that nobody could defend. NOT
    ``TRANSFER`` either: that needs inter-store transfer cost, which is equally absent.

    So the verb is the one the data actually supports. A second value arrives when the data that
    would justify it does — the same union-of-one discipline as ``GateKind`` and ``Gate``.
    """

    REVIEW = "review"


@dataclass(frozen=True)
class Provenance:
    """WHICH SYSTEM produced this action. Required on every action, no exceptions.

    An attribution study six months out asks "did the actions we took change anything". It can
    only answer that if it can tell which actions came from the same system. A rule whose
    threshold moved, or whose underlying capability changed shape, is a DIFFERENT system, and
    comparing across the change silently averages two experiments.

    WHAT IS CAPTURED, and each because it can change the output without anyone noticing:

    - ``declaration_id`` / ``declaration_version`` — which rule, at which revision.
    - ``capability_versions`` — every capability the declaration resolved, at its descriptor
      version. Available because ``DeclarationSatisfied`` carries the resolutions.
    - ``thresholds`` — the actual numbers used, not a reference to them. A threshold read from
      the declaration at analysis time would be re-read later at its NEW value, which is the
      subtle version of the same mistake.
    - ``as_of`` — the date the analysis was evaluated for. Every dead-stock answer is relative
      to a date, and a row without one cannot be re-derived.

    WHAT IS NOT CAPTURED, AND WHY — stated because omitting it silently is the failure this
    class exists to prevent. Synapse cannot record which DIS ``mapping_version_id`` produced the
    canonical rows behind an action: the resolvers deliberately drop DIS write-side provenance
    ("DIS's concern; passing it through would invite the analytics plane to reason about
    ingestion"), and reversing that would thread a column through every projection and every
    action row.

    THE INTENDED ROUTE IS DIS-SIDE AND CHEAPER. The question an attribution study actually asks
    is not "which mapping produced this row" but "DID THE MAPPING CHANGE DURING THE STUDY
    WINDOW" — and that is answerable at analysis time as a join against DIS's own history
    (``config.source_mappings`` versioning and ``audit.events``), without threading anything.
    So this is a recorded boundary with a named route across it, not an open gap.
    """

    declaration_id: str
    declaration_version: str
    capability_versions: Mapping[str, str]
    thresholds: Mapping[str, int]
    as_of: date

    def __post_init__(self) -> None:
        if not self.declaration_id or not self.declaration_version:
            raise ValueError("provenance needs the declaration it came from, and its version")
        if not self.capability_versions:
            raise ValueError(
                "provenance names no capability versions. Every declaration requires at least "
                "one capability (AnalysisDeclaration refuses zero), so an empty mapping here "
                "means the resolutions were dropped on the way rather than that none existed"
            )


@dataclass(frozen=True)
class Action:
    """One thing to do about one finding, with everything needed to analyse it later.

    ``target`` is a mapping of grain column to value rather than a typed tuple, so it reads
    without knowing the analysis: ``{"sku_id": "SKU-1", ...}`` says what it is. It must be
    non-empty — an action with no target is a suggestion.

    ``quantity_at_stake`` IS UNITS, NOT MONEY, and that is a finding rather than a simplification.
    The money figure would be ``stock_qty * unit_cost``, and three things block it:

      1. ``unit_cost`` is resolvable (it is in ``current_state.returns``) but NOT declared in
         dead_stock's requirement — a one-line fix, held back because the other two are not.
      2. Both operands are NULLABLE in canonical, so money would be UNKNOWN for some positions.
      3. Canonical's own comment on ``unit_cost`` says the tax basis is UNDETERMINED: "Tax
         treatment scope TBD: confirm whether this follows the row tax_treatment column or is
         always tax-exclusive by convention." A money figure would carry an unstated tax basis.

    The third is a DIS decision, not Synapse's, and it is the SECOND time canonical's tax
    treatment has blocked money in this plane — ``daily_series`` returns quantity only for the
    same reason. Units are unambiguous and computable today; money waits for a decision that is
    not ours.

    ``None`` means the quantity is UNKNOWN (``stock_qty`` is nullable), never zero. Zero would
    sort a dead position to the bottom of any list built on this, which is the wrong end.

    ``arm`` HAS NO DEFAULT. See ``synapse.core.holdout``.
    """

    target: Mapping[str, str]
    verb: Verb
    quantity_at_stake: Decimal | None
    expires_on: date
    arm: Arm
    provenance: Provenance
    # ------------------------------------------------------------------------
    # OBSERVATIONS, NOT SCORES. The finding's own measure at the moment this action was first
    # recorded, carried so that a future ranking has a history to fit against instead of
    # starting its clock on the day it is scoped. Nothing reads them yet and nothing ranks.
    #
    # ONE PER ANALYSIS, and the other stays None: dead_stock measures days since the last sale,
    # stockout_risk measures days of cover. They are not two views of one quantity, so a single
    # "urgency" field would have had to mean different things depending on the declaration —
    # which is the kind of field that reads as comparable and is not.
    #
    # DEFAULTED, so all ten modules that construct an Action keep working unchanged.
    #
    # FIRST OBSERVATION, NOT LATEST. Neither is in payload_hash's material, so a re-run whose
    # only difference is one of these values is suppressed by uq_actions_idempotency and the
    # stored figure stays the one from the run that landed first. That is correct for
    # idempotency and it is what the column comments in migration 0004 promise.
    days_since_last_sale: int | None = None
    days_of_cover: Decimal | None = None

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("an action with no target is a suggestion, not an action")
        if self.quantity_at_stake is not None and self.quantity_at_stake < 0:
            raise ValueError(
                f"quantity_at_stake is {self.quantity_at_stake}; negative stock is not a "
                "quantity at stake, and None is how 'unknown' is said here"
            )
        if self.expires_on < self.provenance.as_of:
            raise ValueError(
                f"action expires {self.expires_on}, before the {self.provenance.as_of} it was "
                "evaluated for; an action that arrives expired cannot be acted on"
            )
        # NON-NEGATIVITY ONLY. Deliberately nothing that could make an existing construction
        # fail: both fields default to None and every current call site omits them, so this
        # guard can only fire on a value somebody newly supplies.
        #
        # days_since_last_sale CAN legitimately be negative in the evaluator — a clock-skewed
        # POS can date a sale after as_of, and dead_stock passes that through rather than
        # clamping it (see dead_stock.py's note on not hiding the skew). It is refused HERE
        # because a negative age on a RECORDED action is a different thing from a negative
        # intermediate: it would be stored, read back by a future ranking, and silently treated
        # as extremely fresh. The evaluator keeps the skew visible; the log refuses to carry it.
        if self.days_since_last_sale is not None and self.days_since_last_sale < 0:
            raise ValueError(
                f"days_since_last_sale is {self.days_since_last_sale}; a negative age means a "
                "sale dated after as_of, which is source clock skew rather than an observation "
                "worth recording against this action"
            )
        if self.days_of_cover is not None and self.days_of_cover < 0:
            raise ValueError(
                f"days_of_cover is {self.days_of_cover}; cover is stock divided by a rate and "
                "the evaluator refuses every input that could produce a negative"
            )

    @property
    def is_actionable(self) -> bool:
        """Whether there is anything to DO about this action, today, for the platform reader.

        A FLAG, NEVER A FILTER. Nothing in this plane may use it to suppress, reorder or gate the
        recording of an action. The rule is structural: nothing sits between propose and record,
        and the proposers' ``if not finding.is_dead_stock: continue`` is the only filter that
        exists. A low-value action is still a recorded action, because
        attribution needs the whole population and a filter applied before recording destroys the
        denominator.

        THE PREDICATE, and both false cases are false for different reasons:

          ``None``      NOT actionable — the quantity is UNKNOWN. stock_qty is nullable in
                        canonical and dead_stock never inspects it, so a dead position with no
                        stock figure reaches here as None. Nothing can be decided from it.
          ``0``         NOT actionable — VERIFIED nothing to act on. A never-sold SKU with zero
                        stock is real catalogue hygiene, but there is no stock to mark down,
                        transfer or clear.
          ``> 0``       Actionable.

        A BOOL RATHER THAN A TRI-STATE, AND NOTHING IS LOST. The distinction between "unknown"
        and "verified zero" survives in the data: ``quantity_at_stake`` is stored on the row, so
        None, 0 and positive are all recoverable. This bool is a VIEW over a preserved
        distinction, not a lossy encoding of it — anything needing the three-way answer reads the
        quantity directly.

        AUDIENCE-RELATIVE, AND THERE IS NO AUDIENCE IN THE TYPE SYSTEM YET. Whether a zero-stock
        dead SKU is worth surfacing depends on who is reading: it is genuine catalogue hygiene
        for a platform operator and not a decision for a store manager. Nothing here can express
        that — ``Verb`` is a union of one (see the note at action.py:48, which makes the same
        argument for why there is one verb and not three), there is no recipient model, and no
        delivery exists. So THIS DERIVATION ENCODES THE PLATFORM READING ONLY. A tenant-facing
        answer is a different predicate and must not be assumed to be this one.
        """
        return self.quantity_at_stake is not None and self.quantity_at_stake > 0


@dataclass(frozen=True)
class ActionEvent:
    """One append to the log. Frozen, and there is no operation anywhere that edits one.

    A CORRECTION IS A NEW EVENT naming the one it replaces, via ``supersedes``. That is the
    canonical event tables' shape one layer up, and it is chosen for the same reason: an
    append-only log can be replayed
    to any point in time, and an edited row destroys the history that makes a study possible.

    ``event_id`` AND ``recorded_at`` ARE SUPPLIED, not minted here. ``synapse.core`` mints
    nothing: ``uuid4`` is banned project-wide, ``uuidv7`` lives in ``dis_core`` which Synapse
    does not take as a direct dependency, and a pure module that reads the clock cannot be
    tested at a boundary. The same reasoning as ``as_of`` being a parameter on the evaluator.
    """

    event_id: UUID
    recorded_at: datetime
    action: Action
    supersedes: UUID | None = None

    def __post_init__(self) -> None:
        if self.supersedes == self.event_id:
            raise ValueError(f"event {self.event_id} supersedes itself")


__all__ = ["Action", "ActionEvent", "Provenance", "Verb"]
