"""The producer-owned ``connector_run_id`` mint.

Lives here, and NOT in ``dev_transport``, for a packaging reason: ``real_transport``
is the production entrypoint and reused this function, so importing it from
``dev_transport`` dragged ``dev_transport`` — and transitively ``fakes`` — into the
production image's import graph. A dev-only transport and a module of test doubles
have no business in a deployed connector, and the root ``.dockerignore`` now keeps
both out of the image; this module is what lets that exclusion hold.

``real_transport`` and ``dev_transport`` both import from here, so the offline and
real paths still mint identically. That reuse is the point and is asserted by the
transport tests: the two must be the SAME function, never a copy.
"""

from __future__ import annotations

import hashlib


def mint_connector_run_id(
    tenant_id: str, store_id: str, source_id: str, template_id: str, run_key: str
) -> str:
    """Deterministic, producer-owned dedup id. Same inputs + run_key to same id; no wall-clock."""
    material = f"{tenant_id}|{store_id}|{source_id}|{template_id}|{run_key}"
    return "run_" + hashlib.sha256(material.encode()).hexdigest()[:12]
