"""The trigger transport (producer): stable, producer-owned connector_run_id + valid trigger.

Offline, no DB. Proves the run_id is stable per (identity + run_key), distinct for a new
run_key, and that the receiver does not derive it (the producer stamps it; the receiver
reads trigger.connector_run_id).
"""

from __future__ import annotations

import inspect
from uuid import UUID

from thalamus_connector_sdk.adapter import Domain
from thalamus_connector_sdk.trigger import ConnectorTrigger
from thalamus_square.run_id import mint_connector_run_id

_T = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"
_S = "019e5e3c-b633-7344-93c7-83fb205285ea"
_SRC = "square_pos_v2"
_TPL = "019f75ff-141b-7223-98e9-05bbfdcca63d"


def test_run_id_stable_for_same_inputs_and_run_key() -> None:
    # (a) STABILITY, by string equality: no wall-clock enters the derivation.
    a = mint_connector_run_id(_T, _S, _SRC, _TPL, "bootstrap-001")
    b = mint_connector_run_id(_T, _S, _SRC, _TPL, "bootstrap-001")
    assert a == b
    assert a.startswith("run_") and len(a) == 16


def test_run_id_distinct_for_a_new_run_key() -> None:
    # (b) DISTINCTNESS: a new intended run is not collapsed onto the bootstrap id.
    boot = mint_connector_run_id(_T, _S, _SRC, _TPL, "bootstrap-001")
    refresh = mint_connector_run_id(_T, _S, _SRC, _TPL, "refresh-001")
    assert boot != refresh


def test_trigger_is_valid_and_carries_the_producer_run_id() -> None:
    run_id = mint_connector_run_id(_T, _S, _SRC, _TPL, "bootstrap-001")
    trigger = ConnectorTrigger(
        schema_version=1,
        trace_id=UUID("019f7601-5f47-7622-9750-bf7cac2b077b"),
        connector_run_id=run_id,
        tenant_id=UUID(_T),
        store_id=UUID(_S),
        source_id=_SRC,
        template_id=UUID(_TPL),
        domains=[Domain.CATALOG],
        cursor=None,
        store_code="W-001",
    )
    assert trigger.connector_run_id == run_id  # producer-stamped, carried on the trigger
    assert trigger.domains == [Domain.CATALOG]


def test_receiver_does_not_derive_the_run_id() -> None:
    # D54: the receiver reads trigger.connector_run_id; only the producer (this module)
    # derives it. The SDK pipeline must not reference the minting function.
    import thalamus_connector_sdk.pipeline as receiver

    src = inspect.getsource(receiver)
    assert "mint_connector_run_id" not in src
    assert "trigger.connector_run_id" in src  # it READS the trigger's value


def test_run_id_golden_value_is_frozen() -> None:
    """LOAD-BEARING: the DERIVED VALUE, not just its shape.

    connector_run_id drives the pipeline's duplicate_noop. If the derivation ever
    changes, a re-run with the SAME --run-key mints a DIFFERENT id, the dedup lookup
    misses, and the pull silently RE-INGESTS instead of no-opping. Nothing else in the
    suite would notice: the shape assertions (run_ prefix, length) and the
    same-function-object assertion both survive a changed hash.

    The literal below was computed from the unchanged pure function at the moment the
    mint moved out of dev_transport, so it pins today's behaviour rather than blessing a
    drift. If this fails, the question is not "update the literal" - it is whether every
    already-ingested run is about to be re-ingested.
    """
    assert mint_connector_run_id(_T, _S, _SRC, _TPL, "bootstrap-001") == "run_18527fc58d3b"
