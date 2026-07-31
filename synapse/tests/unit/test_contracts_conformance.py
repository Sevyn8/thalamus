"""Runs the Synapse contract conformance harness under pytest.

THIS REPO HAS NO CI — no .github/workflows, no root Makefile, only
dis/.pre-commit-config.yaml and dis/Makefile. So "the harness runs in CI" is not
available as a wiring strategy, and the C6 pack harness's own claim to be CI-run is
aspirational. Invoking it from a test is what actually makes it run today, under
tooling that already exists (`make test`), with `make -C synapse conformance` as the
direct path.

Runs it in-process rather than via subprocess so a failure surfaces the harness's own
[FAIL] lines in pytest output instead of an opaque non-zero exit code.
"""

from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import ModuleType

import pytest

VALIDATE = pathlib.Path(__file__).resolve().parents[3] / "contracts" / "synapse" / "validate.py"


def _load_harness() -> ModuleType:
    spec = importlib.util.spec_from_file_location("synapse_contract_validate", VALIDATE)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_harness_file_exists() -> None:
    assert VALIDATE.is_file(), f"conformance harness missing at {VALIDATE}"


def test_conformance_passes(capsys: pytest.CaptureFixture[str]) -> None:
    harness = _load_harness()
    # The harness accumulates into a module-level list; reset so a re-import inside one
    # pytest session cannot carry failures across.
    harness.failures.clear()
    exit_code = harness.main()
    captured = capsys.readouterr().out
    assert exit_code == 0, f"conformance failed:\n{captured}"
    assert "OK: all conformance checks passed." in captured
