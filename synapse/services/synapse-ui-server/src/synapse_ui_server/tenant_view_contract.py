"""THE TENANT-FACING CONSTRAINT. Not built in 8a; recorded here so 8b cannot miss it.

This module deliberately contains no endpoint. Slice 8a serves PLATFORM only, and the
tenant-facing shadow view (T1) is 8b's, together with the Customer Master module grant it
depends on. What is here is the design that was accepted before either existed, because it is
the item most likely to be got wrong under time pressure and the failure is silent.

==============================================================================
THE CONSTRAINT
==============================================================================
**While ANY analysis is at the SHADOW rung, the tenant endpoint must not return a single
``sku_id``, product name, or store-level breakdown. Counts only.**

WHY IT IS NOT A PRESENTATION CONCERN. A rendered-but-hidden field is still a leak — it is in the
response body, in the browser's memory, and in anything that logs a payload. And the damage is
not embarrassment: a client who acts on a product that was HELD BACK from treatment destroys the
comparison that the holdout exists to create, and it makes no difference whether they were sent
it or went looking for it. The measurement is lost either way, and lost silently: nothing in
``synapse.actions`` records that a control was contaminated.

A COUNT OF STORES IS NOT A STORE-LEVEL BREAKDOWN. "66 products across 2 stores" is a count and
is permitted. "38 in Mokotów, 28 in Praga" is a breakdown and is not. The line is whether a
number can be attributed to a particular store or product, not whether the word "store" appears.

==============================================================================
FOUR LAYERS, AND NONE OF THEM IS "REMEMBER TO CHECK"
==============================================================================

(a) **A SEPARATE READER THAT ISSUES ``COUNT(*)``.** Not fetch-then-filter.
    ``PostgresActionReader._SELECT`` pulls ``target`` — the JSONB carrying ``sku_id`` — for every
    row. A tenant view built on it would hold every identifier in process memory, and one
    serialiser change would ship them. The tenant reader must aggregate IN SQL so the
    identifiers are never selected, never deserialised, and never present to be leaked.

(b) **A RESPONSE TYPE WHOSE FIELDS CANNOT HOLD AN IDENTIFIER.** Scalars and counts only. No
    ``Mapping[str, str]``, no row sequence, no free-form payload — nothing with somewhere to put
    a sku_id even by accident.

(c) **AN IMPORT-LINTER ``forbidden`` CONTRACT: the tenant read module may not import
    ``synapse.core.action``.** This is the layer that turns care into a property. With it, a
    ``sku_id`` is not merely unrendered — the types that carry one are not in scope, so writing
    the leak fails the contract rather than passing review. This repo already runs seven
    forbidden contracts; the mechanism is idiomatic here.

(d) **A RUNG ASSERTION THAT REFUSES RATHER THAN GUESSES.** If any provisioned analysis for the
    acting tenant sits above ``SHADOW``, the endpoint returns an error, not a best guess at what
    is now permissible. The promoted-tenant view (T2) does not exist, and an endpoint that
    silently starts returning more when a rung changes is the same class of failure as a gate
    that stops biting.

==============================================================================
WHY T2 IS NOT BUILT EITHER
==============================================================================
Ranking must exist before delivery. Today's single real action is a zero-stock never-sold SKU —
catalogue hygiene, not a decision — so shipping a client-facing queue now means the first thing
a client ever sees from Synapse is its least interesting finding.

``synapse.core.holdout`` and the ``stockout_risk`` declaration both carry the same trigger for
the related contamination question: THE FIRST ANALYSIS TO LEAVE SHADOW. None of this fires while
everything is at shadow, which is the state 8a preserves.
"""

from __future__ import annotations

from typing import Final

__all__ = ["FORBIDDEN_TENANT_FIELDS", "TENANT_READ_MODULE"]

# Field names that must never appear on a tenant-facing response model. Exported as data so 8b's
# test asserts against THIS list rather than restating it — a restated list is a second source of
# truth, and the copy that drifts is always the one nobody is looking at.
FORBIDDEN_TENANT_FIELDS: Final[frozenset[str]] = frozenset(
    {
        "sku_id",
        "sku",
        "product_name",
        "product",
        "store_id",
        "store_name",
        "target",
        "targets",
        "actions",
        "events",
        "rows",
        "items",
    }
)

# The module the forbidden import-linter contract will name as its source. Declared here so the
# contract, the test and the module cannot disagree about which path is constrained.
TENANT_READ_MODULE: Final[str] = "synapse_ui_server.tenant"
