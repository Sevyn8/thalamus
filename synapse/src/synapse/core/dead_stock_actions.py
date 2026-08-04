"""Turn dead_stock findings into actions. The third instance of the plugin shape.

A capability has a descriptor (data) and a resolver (a function). An analysis has a declaration
(data) and an evaluator (a function). An action proposer is the same shape again: bound in the
registry by id, so adding one is a row plus a function and never an engine edit.

WHY A SEPARATE STAGE AND NOT THE EVALUATOR. ``is_dead_stock`` is a FINDING — a statement about
the world. An action is a statement about what somebody should do, and it carries three things a
finding has no business knowing: an experiment arm, an expiry, and the provenance of the system
that produced it. Folding them into the evaluator would make every future analysis import the
action contract to emit a row, and would put holdout assignment inside arithmetic that has no
reason to know an experiment exists.

WHY NOT IN THE DECLARATION EITHER. A declaration that could express "verb REVIEW when
is_dead_stock" would need a condition language, and inventing one from a single analysis is the
guessing this project has refused five times now.

ONLY FINDINGS THAT ARE DEAD PRODUCE ACTIONS. The evaluator deliberately emits one row per
position so ``is_dead_stock`` carries information; the proposer is where the filter belongs,
because "which findings deserve an action" is an action-layer question.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal

from synapse.core.action import Action, Provenance, Verb
from synapse.core.analysis import AnalysisDeclaration
from synapse.core.current_state import CurrentStateRow
from synapse.core.dead_stock import DeadStockRow
from synapse.core.holdout import assign

# The threshold names this proposer reads. Named as constants so a rename in the declaration
# fails loudly here rather than silently producing actions with a missing expiry.
_STALE_AFTER = "stale_after_days"
_EXPIRES_AFTER = "expires_after_days"


def propose_dead_stock_actions(
    findings: Sequence[DeadStockRow],
    universe: Sequence[CurrentStateRow],
    *,
    declaration: AnalysisDeclaration,
    capability_versions: Mapping[str, str],
    as_of: date,
) -> Sequence[Action]:
    """One REVIEW action per dead position, with its arm and its provenance.

    ``universe`` is needed for ``stock_qty``, which the finding does not carry: the evaluator's
    row is the analysis's declared ``emits``, and quantity-at-stake is an ACTION property rather
    than part of the finding. Joining here costs one dict and keeps ``emits`` stable.

    ``capability_versions`` comes from ``DeclarationSatisfied.capability_versions``, which exists
    because provenance needed it. Passing it in rather than reaching for the registry keeps this
    function pure and testable at any version.

    ``as_of`` IS A PARAMETER, never a clock read — same reason as the evaluator: a function that
    reads the clock cannot be tested at a boundary, and "what would we have said on the 1st" is a
    legitimate question this shape answers for free.

    Raises ``ValueError`` if the declaration is missing the holdout or either threshold, rather
    than producing actions with a fabricated arm or expiry. An action missing either is worse
    than no action: it looks analysable and is not.
    """
    holdout = declaration.holdout
    if holdout is None:
        raise ValueError(
            f"analysis {declaration.id!r} proposes actions but declares no holdout. An action "
            "without an arm can never be analysed, and the counterfactual cannot be added later"
        )
    thresholds = {threshold.name: threshold.days for threshold in declaration.thresholds}
    missing = sorted({_STALE_AFTER, _EXPIRES_AFTER} - set(thresholds))
    if missing:
        raise ValueError(
            f"analysis {declaration.id!r} is missing threshold(s) {missing}, which this proposer "
            "reads by name; producing actions without them would fabricate an expiry"
        )

    stock_by_key: Mapping[tuple[str, str, str], Decimal | None] = {
        (str(row.tenant_id), str(row.store_id), row.sku_id): row.stock_qty for row in universe
    }
    # Recorded ONCE and shared by every action from this run: the provenance of a run is a
    # property of the run, and rebuilding it per row would let two actions from one evaluation
    # disagree about which system produced them.
    provenance = Provenance(
        declaration_id=declaration.id,
        declaration_version=declaration.version,
        capability_versions=dict(capability_versions),
        thresholds=thresholds,
        as_of=as_of,
    )
    expires_on = as_of + timedelta(days=thresholds[_EXPIRES_AFTER])

    actions: list[Action] = []
    for finding in findings:
        if not finding.is_dead_stock:
            continue
        target = {
            "tenant_id": str(finding.tenant_id),
            "store_id": str(finding.store_id),
            "sku_id": finding.sku_id,
        }
        # The subject is the holdout's declared unit, read out of the target in the declared
        # ORDER — the registry checks that every unit column is in the analysis grain, so every
        # one of them is present here.
        subject = tuple(target[column] for column in holdout.unit)
        quantity = stock_by_key.get((target["tenant_id"], target["store_id"], target["sku_id"]))
        actions.append(
            Action(
                target=target,
                verb=Verb.REVIEW,
                # None where stock_qty is NULL. Not zero: see Action's docstring.
                quantity_at_stake=quantity,
                expires_on=expires_on,
                arm=assign(holdout, subject),
                provenance=provenance,
            )
        )
    return actions


__all__ = ["propose_dead_stock_actions"]
