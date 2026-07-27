"""The REAL transport (producer): the pipeline defaults must resolve, offline-provable.

``real_transport`` differs from ``dev_transport`` in exactly one way that matters: it
injects NOTHING into ``build_square_pipeline``, so ``SquarePuller`` + ``VaultTokenStore``
resolve instead of the fakes. That is invisible at import time and would only surface in
staging as an image that silently pulls canned data, so it is asserted here by AST over
the real call site - a re-injected ``token_store=``/``api=`` fails this test.

Offline: no DB, no GCP, no network. Nothing here constructs a pipeline or an engine.
"""

from __future__ import annotations

import ast
import inspect

from thalamus_square import dev_transport, real_transport

_BUILDER = "build_square_pipeline"


def _pipeline_call() -> ast.Call:
    """The single ``build_square_pipeline(...)`` call node in real_transport's source."""
    tree = ast.parse(inspect.getsource(real_transport))
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == _BUILDER
    ]
    assert len(calls) == 1, f"expected exactly one {_BUILDER} call, found {len(calls)}"
    return calls[0]


def test_pipeline_call_injects_neither_token_store_nor_api() -> None:
    # THE point of the module: no injection -> build_square_pipeline resolves its own
    # defaults (the httpx SquarePuller and the Secret Manager VaultTokenStore).
    call = _pipeline_call()
    # A **kwargs splat carries no resolvable name and would defeat the check below.
    assert not any(kw.arg is None for kw in call.keywords), "no **kwargs splat at this call site"
    keywords = {kw.arg for kw in call.keywords if kw.arg is not None}
    assert "token_store" not in keywords, "real transport must NOT inject a token store"
    assert "api" not in keywords, "real transport must NOT inject a Square API client"
    assert keywords == {"engine"}, f"only engine is caller-owned; got {sorted(keywords)}"


def test_no_fakes_are_imported() -> None:
    # A fake reaching the real path any other way (a module-level default, a helper) is
    # the same failure with a different shape.
    source = inspect.getsource(real_transport)
    assert "fakes" not in source
    assert "FakeSquareApi" not in source
    assert "FakeTokenStore" not in source


def test_run_id_derivation_is_reused_not_copied() -> None:
    # Same function OBJECT: the offline and online paths cannot drift on the dedup id.
    # Reached through vars(): real_transport does not RE-export the name (mypy --strict
    # forbids the attribute access, ruff B009 forbids the getattr).
    assert vars(real_transport)["mint_connector_run_id"] is dev_transport.mint_connector_run_id
    assert "def mint_connector_run_id" not in inspect.getsource(real_transport)


def test_cli_declares_the_job_arg_contract() -> None:
    # The Cloud Run Job container carries NO baked args: the run target arrives per
    # execution via `gcloud run jobs execute --args`. These five being required is what
    # makes a bare execute fail loudly (exit 2) instead of pulling against nothing.
    tree = ast.parse(inspect.getsource(real_transport.main))
    declared: dict[str, bool] = {}
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)):
            continue
        if node.func.attr != "add_argument" or not node.args:
            continue
        flag = node.args[0]
        if not isinstance(flag, ast.Constant) or not isinstance(flag.value, str):
            continue
        required = any(
            kw.arg == "required" and isinstance(kw.value, ast.Constant) and kw.value.value is True
            for kw in node.keywords
        )
        declared[flag.value] = required

    assert declared == {
        "--tenant-id": True,
        "--store-id": True,
        "--source-id": True,
        "--template-id": True,
        "--run-key": True,
        "--store-code": False,
    }
