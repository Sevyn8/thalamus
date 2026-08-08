"""Turn overstock findings into actions. The fourth instance of the plugin shape.

ONLY OVERSTOCKED FINDINGS PRODUCE ACTIONS. The evaluator emits one row per position so
``is_overstocked`` carries information; the filter belongs here, because "which findings deserve
an action" is an action-layer question.

THE VERB IS REVIEW, the one that already exists. An operator asked to look at capital sitting
still is doing the same KIND of thing as one asked to look at stock that will not sell -- and
inventing a second verb from one new analysis is the guessing this project has refused
repeatedly. M3 is where a verb question genuinely arises, because a suggested price is a
different act.

quantity_at_stake IS UNITS, matching both existing proposers. The money figure travels as
``retail_value_locked``, which is a separate column with its own semantics, so nothing has to
guess whether a number is a count or a currency.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, timedelta
from decimal import Decimal

from synapse.core.action import Action, Provenance, Verb
from synapse.core.analysis import AnalysisDeclaration
from synapse.core.current_state import CurrentStateRow
from synapse.core.holdout import assign
from synapse.core.overstock import OverstockRow

__all__ = ["propose_overstock_actions"]

_OVERSTOCK_AFTER = "overstock_after_days"
_EXPIRES_AFTER = "expires_after_days"


def propose_overstock_actions(
    findings: Sequence[OverstockRow],
    universe: Sequence[CurrentStateRow],
    *,
    declaration: AnalysisDeclaration,
    capability_versions: Mapping[str, str],
    as_of: date,
) -> Sequence[Action]:
    """One REVIEW action per overstocked position, with its arm and its provenance."""
    holdout = declaration.holdout
    if holdout is None:
        raise ValueError(
            f"analysis {declaration.id!r} proposes actions but declares no holdout. An action "
            "without an arm can never be analysed, and the counterfactual cannot be added later"
        )
    thresholds = {threshold.name: threshold.days for threshold in declaration.thresholds}
    missing = sorted({_OVERSTOCK_AFTER, _EXPIRES_AFTER} - set(thresholds))
    if missing:
        raise ValueError(
            f"analysis {declaration.id!r} is missing threshold(s) {missing}, which this proposer "
            "reads by name; producing actions without them would fabricate an expiry"
        )

    stock_by_key: Mapping[tuple[str, str, str], Decimal | None] = {
        (str(row.tenant_id), str(row.store_id), row.sku_id): row.stock_qty for row in universe
    }
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
        if not finding.is_overstocked:
            continue
        target = {
            "tenant_id": str(finding.tenant_id),
            "store_id": str(finding.store_id),
            "sku_id": finding.sku_id,
        }
        subject = tuple(target[column] for column in holdout.unit)
        actions.append(
            Action(
                target=target,
                verb=Verb.REVIEW,
                quantity_at_stake=stock_by_key.get(
                    (target["tenant_id"], target["store_id"], target["sku_id"])
                ),
                expires_on=expires_on,
                arm=assign(holdout, subject),
                provenance=provenance,
                # The finding's own measures, carried so a future ranking has a history to fit
                # against. Neither is a score and nothing reads them yet.
                days_of_cover=finding.days_of_cover,
                retail_value_locked=finding.retail_value_locked,
            )
        )
    return actions
