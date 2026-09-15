"""P1-SEC-001: the deployment definitions must not be able to turn the dev stub on.

config.py refuses STUB without ``DIS_ALLOW_STUB_AUTH``, and tests/unit/test_stub_auth_policy.py
pins that. This file asserts the other half: that nothing in the deployed configuration SETS
it. Those are different failures. A service that correctly demands the opt-in is still
compromised the day somebody adds the opt-in to a Terraform module "to fix the crashloop", and
nothing in the application would object — from inside the process that variable looks exactly
like a developer's laptop.

Read from the repository text rather than from a live project, deliberately: a live read tells
you about today's deployment, and this needs to fail in the pull request that introduces the
variable, before any deploy happens.
"""

from __future__ import annotations

import re
from pathlib import Path

# services/dis-ui-server/tests/unit/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[5]
_INFRA = _REPO_ROOT / "infra"
_DIS_DOCKER = _REPO_ROOT / "dis" / "terraform" / "docker"
_UI_SERVER_MODULE = _INFRA / "modules" / "cloud-run-service-dis-ui-server"

_STUB_PERMISSION = "DIS_ALLOW_STUB_AUTH"


def test_the_paths_this_test_reads_exist() -> None:
    """Vacuity guard: a moved directory would make every scan below pass against nothing."""
    assert _INFRA.is_dir(), f"{_INFRA} not found; update the constants rather than deleting this test"
    assert _UI_SERVER_MODULE.is_dir(), f"{_UI_SERVER_MODULE} not found"
    assert _DIS_DOCKER.is_dir(), f"{_DIS_DOCKER} not found"
    assert list(_INFRA.rglob("*.tf")), "no terraform files found under infra/"


def test_no_terraform_anywhere_grants_the_stub_permission() -> None:
    """The whole estate, not just the DIS module: the variable is meaningless elsewhere, so
    its appearance anywhere in infrastructure is a mistake worth catching at review time."""
    offenders = [
        f"{path.relative_to(_REPO_ROOT)}:{number}"
        for path in sorted(_INFRA.rglob("*.tf"))
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _STUB_PERMISSION in line
    ]
    assert offenders == [], (
        f"{_STUB_PERMISSION} appears in Terraform at {offenders}. It is the declaration that a "
        "process is local; granting it to a deployed service would let DIS_AUTH_MODE=STUB "
        "select a verifier that accepts tokens signed with a published constant."
    )


def test_no_dis_container_definition_grants_the_stub_permission() -> None:
    """Dockerfiles and Cloud Build configs are deployment definitions too."""
    offenders = [
        f"{path.relative_to(_REPO_ROOT)}:{number}"
        for path in sorted(_DIS_DOCKER.iterdir())
        if path.is_file()
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if _STUB_PERMISSION in line
    ]
    assert offenders == [], f"{_STUB_PERMISSION} appears in a container definition at {offenders}"


def test_the_ui_server_module_still_defaults_to_auth0() -> None:
    """The module default is the last line of defence if a deployment omits the variable.

    config.py already defaults to AUTH0, so this is belt and braces — but the two were written
    years apart and the application default was STUB once. Asserting both means neither can
    drift back alone.
    """
    variables = (_UI_SERVER_MODULE / "variables.tf").read_text(encoding="utf-8")
    block = re.search(r'variable\s+"dis_auth_mode"\s*\{(.*?)\n\}', variables, re.DOTALL)
    assert block is not None, "variable dis_auth_mode is gone from the dis-ui-server module"
    default = re.search(r'default\s*=\s*"([^"]*)"', block.group(1))
    assert default is not None, "dis_auth_mode lost its default; an omitted value would be an error"
    assert default.group(1) == "AUTH0", (
        f"dis-ui-server's Terraform default is {default.group(1)!r}, not 'AUTH0'. The dev stub "
        "accepts tokens signed with a published constant."
    )


def test_the_local_env_contract_documents_both_stub_conditions() -> None:
    """dis/.env.example is the sanctioned local posture and the one place the opt-in belongs.

    Asserted so the developer workflow is not quietly removed to make the scans above green:
    local fixture auth is a supported workflow, not collateral.
    """
    env_example = (_REPO_ROOT / "dis" / ".env.example").read_text(encoding="utf-8")
    assert "DIS_AUTH_MODE=STUB" in env_example
    assert f"{_STUB_PERMISSION}=1" in env_example
