"""Trust-boundary scope proofs (D54, hard rule 4): the SDK holds no Identity Service
dependency and no trace_id minting surface.

Mirrors csv-ingest-worker's ``test_trust_boundary``: a test cannot prove a behaviour's
absence in general, but the import graph and the source surface ARE expressible. The
behavioural half (the published trace equals the trigger's) lives in ``test_pipeline``.
"""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

import thalamus_connector_sdk

_PACKAGE_DIR = Path(str(thalamus_connector_sdk.__file__)).parent
_SOURCES = sorted(_PACKAGE_DIR.glob("*.py"))


def test_package_has_sources() -> None:
    assert len(_SOURCES) >= 9  # the collection guard for the scans below


def _imports_and_names(source: Path) -> tuple[set[str], set[str]]:
    """(imported module paths, every Name/Attribute identifier) - docstrings excluded."""
    tree = ast.parse(source.read_text())
    modules: set[str] = set()
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
    return modules, names


def test_no_module_imports_identity_service_surface() -> None:
    # D54: the connector reads identity off the trigger; no Identity Service client,
    # no resolve call, no external-to-internal translation.
    for source in _SOURCES:
        modules, names = _imports_and_names(source)
        assert not any(m.startswith("dis_core.identity") for m in modules), (
            f"{source.name} imports dis_core.identity (D54 violation)"
        )
        for forbidden in ("resolve_from_upload", "resolve_from_token"):
            assert forbidden not in names, f"{source.name} references {forbidden!r} (D54 violation)"


def test_no_module_references_the_trace_mint() -> None:
    # hard rule 4: trace_id is read off the trigger; new_trace_id must not be
    # imported or referenced. (new_uuid7 for the bronze row id is sanctioned.)
    for source in _SOURCES:
        _, names = _imports_and_names(source)
        assert "new_trace_id" not in names, f"{source.name} references the trace mint"


def test_importing_the_sdk_loads_no_identity_module() -> None:
    # In a fresh interpreter, importing the SDK (which pulls the reused csv-worker
    # bronze/publisher seams) must not load dis_core.identity.
    code = (
        "import sys;"
        "import thalamus_connector_sdk;"
        "import thalamus_connector_sdk.pipeline;"
        "assert 'dis_core.identity' not in sys.modules,"
        " sorted(m for m in sys.modules if m.startswith('dis_core'))"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, check=False)
    assert result.returncode == 0, result.stderr
