"""The transports: a stable producer-owned run id, and the REAL path resolving defaults.

``real_transport`` differs from ``dev_transport`` in exactly one way that matters: it
injects NOTHING into ``build_clover_pipeline``, so ``CloverPuller`` + ``CloverTokenStore``
resolve instead of the fakes. That is invisible at import time and would only surface in
staging as an image that silently pulls canned data, so it is asserted here by AST over the
real call site (D5).

Offline: no DB, no GCP, no network. Nothing here constructs a pipeline or an engine.
"""

from __future__ import annotations

import ast
import inspect
from uuid import UUID

from thalamus_clover import dev_transport, real_transport
from thalamus_clover.dev_transport import mint_connector_run_id
from thalamus_connector_sdk.adapter import Domain
from thalamus_connector_sdk.trigger import ConnectorTrigger

_BUILDER = "build_clover_pipeline"

_T = "019f9d6d-c032-7e03-a232-ee77299f9b5d"
_S = "019f9d71-b356-7caf-8c56-04e5ba6670d0"
_SRC = "clover_pos_v1"
_TPL = "019fa1a9-51dc-77d0-bc4e-2f1088ec693d"


def _pipeline_call(module: object) -> ast.Call:
    tree = ast.parse(inspect.getsource(module))  # type: ignore[arg-type]
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == _BUILDER
    ]
    assert len(calls) == 1, f"expected exactly one {_BUILDER} call, found {len(calls)}"
    return calls[0]


# -- the run id ---------------------------------------------------------------------------


def test_run_id_stable_for_same_inputs_and_run_key() -> None:
    # STABILITY, by string equality: no wall-clock enters the derivation.
    a = mint_connector_run_id(_T, _S, _SRC, _TPL, "bootstrap-001")
    b = mint_connector_run_id(_T, _S, _SRC, _TPL, "bootstrap-001")
    assert a == b
    assert a.startswith("run_") and len(a) == 16


def test_run_id_distinct_for_a_new_run_key() -> None:
    boot = mint_connector_run_id(_T, _S, _SRC, _TPL, "bootstrap-001")
    refresh = mint_connector_run_id(_T, _S, _SRC, _TPL, "refresh-001")
    assert boot != refresh


def test_run_id_derivation_is_reused_not_copied() -> None:
    # Same function OBJECT: the offline and online paths cannot drift on the dedup id.
    # Reached through vars(): real_transport does not RE-export the name (mypy --strict
    # forbids the attribute access, ruff B009 forbids the getattr).
    assert vars(real_transport)["mint_connector_run_id"] is dev_transport.mint_connector_run_id
    assert "def mint_connector_run_id" not in inspect.getsource(real_transport)


# -- the offline/online switch (D5) ----------------------------------------------------------


def test_real_transport_injects_neither_token_store_nor_api() -> None:
    # THE point of the module: no injection -> build_clover_pipeline resolves its own
    # defaults (the httpx CloverPuller and the Secret Manager CloverTokenStore).
    call = _pipeline_call(real_transport)
    assert not any(kw.arg is None for kw in call.keywords), "no **kwargs splat at this call site"
    keywords = {kw.arg for kw in call.keywords if kw.arg is not None}
    assert "token_store" not in keywords, "real transport must NOT inject a token store"
    assert "api" not in keywords, "real transport must NOT inject a Clover API client"
    assert keywords == {"engine"}, f"only engine is caller-owned; got {sorted(keywords)}"


def test_real_transport_imports_no_fakes() -> None:
    source = inspect.getsource(real_transport)
    assert "fakes" not in source
    assert "FakeCloverApi" not in source
    assert "FakeSessionStore" not in source


def test_dev_transport_does_inject_both_fakes() -> None:
    # The inverse guard: if dev_transport ever stopped injecting, it would silently start
    # making live vendor calls from the offline path.
    keywords = {kw.arg for kw in _pipeline_call(dev_transport).keywords}
    assert {"token_store", "api"} <= keywords


# -- the trigger contract ----------------------------------------------------------------------


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
        store_code="AMB-001",
    )
    assert trigger.connector_run_id == run_id  # producer-stamped, carried on the trigger
    assert trigger.domains == [Domain.CATALOG]


def test_both_transports_declare_the_same_arg_contract() -> None:
    expected = {
        "--tenant-id": True,
        "--store-id": True,
        "--source-id": True,
        "--template-id": True,
        "--run-key": True,
        "--store-code": False,
    }
    for module in (dev_transport, real_transport):
        tree = ast.parse(inspect.getsource(module.main))
        declared: dict[str, bool] = {}
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
                continue
            if node.func.attr != "add_argument" or not node.args:
                continue
            flag = node.args[0]
            if not isinstance(flag, ast.Constant) or not isinstance(flag.value, str):
                continue
            declared[flag.value] = any(
                kw.arg == "required" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in node.keywords
            )
        assert declared == expected, module.__name__
