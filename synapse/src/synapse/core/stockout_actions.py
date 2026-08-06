"""One REVIEW action per position at risk of stocking out.

MIRRORS ``propose_dead_stock_actions`` DELIBERATELY, and the mirroring is the test: this is the
second proposer, so anything the action contract got wrong from one example should surface here.
So far it has not — ``Action``, ``Provenance`` and the holdout assignment all took a second
analysis unchanged, which is the structural half of the contract doing its job.

A REFUSED ROW NEVER BECOMES AN ACTION. The evaluator emits one row per position, assessed or
refused, and ``StockoutRiskRow.__post_init__`` already makes "refused AND at risk" unconstructible
— so the filter here is a second, cheaper expression of a property the type already guarantees
rather than the only thing standing between a refusal and an action.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta

from synapse.core.action import Action, Provenance, Verb
from synapse.core.analysis import AnalysisDeclaration
from synapse.core.current_state import CurrentStateRow
from synapse.core.holdout import assign
from synapse.core.stockout_risk import StockoutRiskRow

__all__ = ["propose_stockout_actions"]

_AT_RISK_BELOW = "at_risk_below_days"
_EXPIRES_AFTER = "expires_after_days"


def propose_stockout_actions(
    findings: Sequence[StockoutRiskRow],
    universe: Sequence[CurrentStateRow],
    *,
    declaration: AnalysisDeclaration,
    capability_versions: Mapping[str, str],
    as_of: date,
) -> Sequence[Action]:
    """One REVIEW action per at-risk position, with its arm and its provenance.

    ``universe`` supplies ``stock_qty`` for ``quantity_at_stake``, exactly as the dead_stock
    proposer does: the finding carries the analysis's declared ``emits`` and quantity-at-stake is
    an ACTION property, not part of the finding.

    ``as_of`` IS A PARAMETER, never a clock read. It is also the SLOT when the orchestrator calls
    this, which is what makes a redelivered dispatch produce byte-identical actions and lets the
    idempotency index suppress them.

    Raises ``ValueError`` rather than producing actions with a fabricated arm or expiry — an
    action missing either looks analysable and is not.
    """
    holdout = declaration.holdout
    if holdout is None:
        raise ValueError(
            f"analysis {declaration.id!r} proposes actions but declares no holdout. An action "
            "without an arm can never be analysed, and the counterfactual cannot be added later"
        )
    thresholds = {threshold.name: threshold.days for threshold in declaration.thresholds}
    missing = sorted({_AT_RISK_BELOW, _EXPIRES_AFTER} - set(thresholds))
    if missing:
        raise ValueError(
            f"analysis {declaration.id!r} is missing threshold(s) {missing}, which this proposer "
            "reads by name; producing actions without them would fabricate an expiry"
        )

    stock_by_key = {(str(row.tenant_id), str(row.store_id), row.sku_id): row.stock_qty for row in universe}
    # Built ONCE and shared by every action from this run: provenance is a property of the run,
    # and rebuilding it per row would let two actions from one evaluation disagree about which
    # system produced them.
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
        if not finding.is_at_risk:
            continue
        target = {
            "tenant_id": str(finding.tenant_id),
            "store_id": str(finding.store_id),
            "sku_id": finding.sku_id,
        }
        # The subject is the holdout's declared unit read out of the target IN THE DECLARED
        # ORDER. The registry checks every unit column is in the analysis grain, so each is here.
        subject = tuple(target[column] for column in holdout.unit)
        actions.append(
            Action(
                target=target,
                verb=Verb.REVIEW,
                # The units at stake are what is still ON HAND — that is what runs out. None
                # where stock_qty is NULL, though a NULL-stock position is refused upstream and
                # cannot reach here.
                quantity_at_stake=stock_by_key.get(
                    (target["tenant_id"], target["store_id"], target["sku_id"])
                ),
                expires_on=expires_on,
                arm=assign(holdout, subject),
                provenance=provenance,
                # stockout_risk does not compute a last-sale age. See migration 0004's comment.
                days_since_last_sale=None,
                # THE FINDING'S OWN MEASURE. An at-risk row is never a refusal, and
                # StockoutRiskRow.__post_init__ makes "refused with a cover figure"
                # unconstructible, so this is non-None and non-negative by the time it is read.
                days_of_cover=finding.days_of_cover,
            )
        )
    return actions
