"""This service must never be anonymously invocable. Checked, not asserted in a comment.

WHY THESE LIVE IN A PYTHON SUITE AND NOT IN TERRAFORM. There is a terraform-level guard too — a
``lifecycle.precondition`` on the invoker binding — and it is the primary one, because it refuses
at PLAN time and cannot be reached by an apply. But a precondition only sees the resource it is
attached to. A SECOND binding added elsewhere in the module, with allUsers, would never pass
through it. These read the whole file instead. Two checks because there are two ways in.

THE HISTORY THEY EXIST FOR. This service originally carried
``ingress = INGRESS_TRAFFIC_INTERNAL_ONLY``, which was never satisfiable: its only caller,
cm-frontend, has no VPC connector and no direct VPC egress, so every request left over the public
internet and was refused at the edge with a 404 and no log at either end. Ingress was relaxed to
INGRESS_TRAFFIC_ALL rather than routing cm-frontend's entire Auth0 path through a three-instance
connector. What that gave up is the layer that FAILS CLOSED when somebody adds an anonymous
binding — the standing HIGH finding, already true of four other HTTP services in this estate.
These tests are the replacement, aimed at that specific failure mode.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

# synapse/services/synapse-ui-server/tests/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MODULE = _REPO_ROOT / "infra" / "modules" / "cloud-run-service-synapse-ui-server" / "main.tf"

_ANONYMOUS = ("allUsers", "allAuthenticatedUsers")


def _strip_lifecycle_blocks(source: str) -> str:
    """Remove balanced ``lifecycle { ... }`` blocks.

    THE GUARD NAMES WHAT IT FORBIDS. The precondition's condition is
    ``!contains(["allUsers", "allAuthenticatedUsers"], ...)`` — the deny-list has to appear
    literally for the check to work. Scanning it alongside real configuration reports the
    machinery as the offence, which is exactly the shape of "a guard whose scope does not match
    its claim": the broad test below claims to find anonymous BINDINGS and would have been
    reporting an anonymous *string*. Caught by running it, not by reading it.

    A lifecycle block cannot create an IAM binding, so nothing checkable is lost.
    """
    out: list[str] = []
    index = 0
    while True:
        match = re.search(r"\blifecycle\s*\{", source[index:])
        if match is None:
            out.append(source[index:])
            return "".join(out)
        start = index + match.start()
        out.append(source[index:start])
        depth = 0
        cursor = index + match.end() - 1  # at the opening brace
        while cursor < len(source):
            if source[cursor] == "{":
                depth += 1
            elif source[cursor] == "}":
                depth -= 1
                if depth == 0:
                    break
            cursor += 1
        index = cursor + 1


def _terraform_code(*, keep_lifecycle: bool = True) -> str:
    """The module with comments and heredoc bodies removed, leaving only what terraform acts on.

    Both must go. The header discusses allUsers at length in order to explain why there is none,
    and the precondition's error_message names it too — so a naive scan of the raw file would flag
    the very machinery that prevents the thing.
    """
    source = _MODULE.read_text(encoding="utf-8")
    # Heredocs first: their bodies can contain anything, including '#'.
    source = re.sub(r"<<-?(\w+)\n.*?^\s*\1\b", "", source, flags=re.DOTALL | re.MULTILINE)
    if not keep_lifecycle:
        source = _strip_lifecycle_blocks(source)
    return "\n".join(line for line in source.splitlines() if not line.strip().startswith(("#", "//")))


def test_the_terraform_module_is_where_this_test_thinks_it_is() -> None:
    """THE VACUITY GUARD, and it is not ceremony.

    Every check below reads one file. If the module is moved or renamed, a path that no longer
    resolves would make all of them pass against an empty string — the "0 == 0 proves nothing"
    failure this project has already paid for. Absence is a failure here, not a pass.
    """
    assert _MODULE.is_file(), (
        f"{_MODULE} not found. If the module moved, update _MODULE — do not delete these tests; "
        "they are the only thing standing between this service and an anonymous invoker binding."
    )
    # And that it is the RIGHT file, not merely a file.
    assert "google_cloud_run_v2_service" in _MODULE.read_text(encoding="utf-8")


def test_no_iam_binding_grants_invoke_to_an_anonymous_principal() -> None:
    """THE ONE THAT MATTERS. Scoped to member assignments, which is the only place an IAM
    principal can actually be named — precise enough that prose about allUsers cannot trip it and
    a real binding cannot hide from it."""
    offenders: list[str] = []
    for number, line in enumerate(_terraform_code().splitlines(), start=1):
        if re.search(r"\bmembers?\s*=", line):
            for principal in _ANONYMOUS:
                if principal in line:
                    offenders.append(f"line {number}: {line.strip()}")
    assert offenders == [], (
        "synapse-ui-server would be publicly invocable. Ingress is INGRESS_TRAFFIC_ALL, so IAM is "
        f"the only network-layer control left: {offenders}"
    )


def test_no_anonymous_principal_appears_anywhere_in_the_module_code() -> None:
    """The broad backstop. The test above knows what an IAM binding looks like today; this one
    does not need to. A future resource type, or a local, or a variable default that renders to
    allUsers, fails here even if it never matches ``member =``."""
    code = _terraform_code(keep_lifecycle=False)
    found = [principal for principal in _ANONYMOUS if principal in code]
    assert found == [], (
        f"{found} appears in the module's executable configuration. If this is deliberate, it "
        "needs its own commit and a stated reason — not a line inside another change."
    )


def test_the_terraform_precondition_still_exists() -> None:
    """A guard that can be silently deleted is not a guard.

    The precondition is the PRIMARY control — it fails `terraform plan`, so it stops an apply that
    these tests would only catch if somebody ran them. Deleting it while leaving these behind
    would quietly downgrade a plan-time refusal into a test somebody has to remember to run, in a
    repo with no CI.
    """
    code = _terraform_code()
    assert "precondition" in code, (
        "the lifecycle.precondition on the invoker binding is gone. It is the plan-time half of "
        "this guard and there is no CI to run the pytest half."
    )
    assert "allUsers" in _MODULE.read_text(encoding="utf-8"), (
        "the precondition no longer references allUsers; check it still asserts what it claims"
    )


def test_every_secret_iam_member_is_listed_in_the_services_depends_on() -> None:
    """PAIR #14, WHICH ONCE COST TWO DAYS OF A DEAD WRITE PATH IN PRODUCTION.

    THE FAILURE THIS CATCHES. The env blocks reference
    ``data.google_secret_manager_secret.*.secret_id``, which is the DATA SOURCE. Terraform sees an
    edge to the data source and NO EDGE AT ALL to the ``secret_iam_member``, so it is free to
    create the revision before the grant exists or propagates. The container then cannot read its
    own credential, and on this service every DSN is required at startup, so the result is a
    failed health check while the previous revision keeps serving. The apply is green. Nothing in
    the plan says a thing.

    ``depends_on`` is the fix and it is invisible: it is a list somebody has to remember to extend
    when they add a secret, in a file where the addition looks complete without it. That is
    exactly the shape of an inter-artifact pair, so it gets a checker rather than a convention.

    PARSED FROM THE MODULE rather than hardcoded, so a fourth secret is covered the day it lands.
    """
    code = _terraform_code()

    declared = set(re.findall(r'resource\s+"google_secret_manager_secret_iam_member"\s+"([a-z0-9_]+)"', code))
    assert declared, "parsed zero secret iam_members; the regex has stopped biting"

    depends_block = re.search(r"depends_on\s*=\s*\[(.*?)\]", code, re.DOTALL)
    assert depends_block is not None, (
        "the Cloud Run service has no depends_on at all. Every secret grant in this module must "
        "be listed there, or a revision can be created before it can read its own DSN."
    )
    listed = set(re.findall(r"google_secret_manager_secret_iam_member\.([a-z0-9_]+)", depends_block.group(1)))

    missing = sorted(declared - listed)
    assert not missing, (
        f"these secret grants are not in the service's depends_on: {missing}. Terraform will not "
        "infer the ordering, because the env blocks reference the DATA SOURCE and not the grant. "
        "The revision can be created before the grant propagates, the container cannot read its "
        "own credential, and it fails readiness behind an apply that reported success."
    )


def test_the_guard_is_required_because_ingress_is_open() -> None:
    """THE COUPLING, MADE EXPLICIT. These tests replace a specific thing: ingress failing closed.

    So the invariant is conditional, and stating it that way is what keeps the two in step. If
    ingress is ever restored to INTERNAL_ONLY *and its caller is actually given VPC egress*, the
    precondition becomes belt rather than sole control — and this test says so instead of silently
    over-asserting. If ingress is open, the guard is mandatory.
    """
    code = _terraform_code()
    open_ingress = "INGRESS_TRAFFIC_ALL" in code
    internal_ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY" in code
    assert open_ingress != internal_ingress, "ingress is unset or set twice; read the module"

    if open_ingress:
        assert "precondition" in code, (
            "ingress is INGRESS_TRAFFIC_ALL and the invoker precondition is missing. Open ingress "
            "is only defensible while IAM is guarded; this combination is the standing HIGH "
            "finding."
        )
    else:
        pytest.fail(
            "ingress is INTERNAL_ONLY again. Before this is correct, verify the CALLER can "
            "satisfy it: cm-frontend needs a VPC connector or direct VPC egress with "
            "ALL_TRAFFIC, and had neither when this was first shipped. An unsatisfiable ingress "
            "rule fails at the edge with 404 and logs at neither end. Delete this branch "
            "deliberately once the caller is verified."
        )


# ===============================================================================================
# P1-IAM-001A: the invoker binding names cm-frontend's OWN identity, and the broad legacy member
# is retained temporarily and visibly. These assert the migration state, not the target state.
# ===============================================================================================
_DEFAULT_COMPUTE = re.compile(r"\d+-compute@developer\.gserviceaccount\.com")


def test_the_dedicated_caller_binding_exists() -> None:
    """The binding that SURVIVES Stage B, asserted by name.

    The parity between "a caller is bound" and "the RIGHT caller is bound" is the whole point of
    this tranche: before it, one binding named a shared identity and the module's own header said
    so. If a future edit collapses the two bindings back into one, this fails rather than the
    estate quietly returning to a single broad member.
    """
    code = _terraform_code()
    assert 'resource "google_cloud_run_v2_service_iam_member" "dedicated_frontend_invoker"' in code, (
        "the dedicated cm-frontend invoker binding is gone. Synapse would then admit only the "
        "legacy default-compute member, which is the posture P1-IAM-001A exists to leave."
    )
    assert "var.caller_service_account_email" in code


def test_the_dedicated_caller_is_not_a_default_compute_account() -> None:
    """The caller variable must not be wired back to the shared identity.

    Terraform's own `validation` block on the variable is the primary gate and refuses at plan.
    This is the file-level half: a validation block can be deleted in the same commit that
    reintroduces the address, and then nothing would object.
    """
    variables = (_MODULE.parent / "variables.tf").read_text(encoding="utf-8")
    block = re.search(r'variable\s+"caller_service_account_email"\s*\{(.*?)\n\}', variables, re.DOTALL)
    assert block is not None, "variable caller_service_account_email is gone; read the module"
    assert "validation" in block.group(1), (
        "the caller variable lost its validation block. Without it, passing the default compute "
        "SA back in is a one-line change that no gate refuses."
    )


def test_the_legacy_member_is_named_for_what_it_is_and_marked_temporary() -> None:
    """THE POINT OF THE NAMING, AND IT IS NOT COSMETIC.

    This member was called `frontend_invoker` while holding the project's default compute
    identity, which is how a binding that admits every default-compute workload read as "the
    frontend's binding" for months. Stage A renames it to say what it is and dates it. A rename
    back, or a removal of the removal-date comment, is how this quietly becomes permanent.
    """
    code = _terraform_code()
    assert 'resource "google_cloud_run_v2_service_iam_member" "legacy_default_compute_invoker"' in code, (
        "the legacy member is no longer declared under its explicit name. If Stage B removed it, "
        "delete this test in the same commit; if it was merely renamed, put the name back."
    )
    # The RAW file, not _terraform_code(): the marker is deliberately a comment, and
    # _terraform_code() strips comments so that prose about allUsers cannot trip the scan above.
    assert "REMOVE IN P1-IAM-001B" in _MODULE.read_text(encoding="utf-8"), (
        "the legacy invoker lost its removal marker. A temporary broad grant with no stated end "
        "is a permanent broad grant."
    )
    assert "var.legacy_caller_service_account_email" in code, (
        "the legacy member no longer reads its own variable. Sharing the caller variable would "
        "hide the broad principal behind the dedicated one's name."
    )


def test_the_default_compute_address_appears_only_on_the_legacy_path() -> None:
    """A literal default-compute address anywhere else in this module would be a second broad
    grant wearing a different name. The legacy binding reads a variable, so the address itself
    should not be written in this file at all."""
    offenders = [
        f"line {n}: {line.strip()}"
        for n, line in enumerate(_terraform_code().splitlines(), start=1)
        if _DEFAULT_COMPUTE.search(line)
    ]
    assert offenders == [], (
        f"a default-compute service account address is hardcoded in this module: {offenders}. "
        "The legacy member is passed in as legacy_caller_service_account_email precisely so the "
        "address appears once, at the call site, where it is reviewed."
    )


def test_both_invoker_bindings_carry_the_anonymous_principal_guard() -> None:
    """TWO BINDINGS NOW, SO TWO GUARDS.

    The original precondition/postcondition pair protected the only invoker binding in the file.
    Adding a second one without its own guard would leave the newer binding - the one that stays
    after Stage B, and therefore the one future changes will touch - unprotected, while the file
    still visibly contained a guard.
    """
    code = _terraform_code()
    bindings = re.findall(r'resource\s+"google_cloud_run_v2_service_iam_member"\s+"([a-z0-9_]+)"', code)
    assert len(bindings) == 2, f"expected exactly two invoker bindings during Stage A, found {bindings}"
    assert code.count("precondition") == len(bindings), (
        f"{len(bindings)} invoker bindings but {code.count('precondition')} preconditions; one "
        "binding can be granted an anonymous principal without any guard refusing"
    )
    assert code.count("postcondition") == len(bindings), (
        f"{len(bindings)} invoker bindings but {code.count('postcondition')} postconditions; a "
        "hardcoded member would bypass the remaining guard"
    )


def test_the_legacy_rename_carries_its_state_across() -> None:
    """A `moved` block, not a destroy and recreate.

    Renaming an iam_member resource without one deletes the binding and creates it again. The
    member being deleted is the one the SERVING cm-frontend revision depends on, so the window
    between the two operations is a window where the live console 403s - the exact outage this
    staged rollout is shaped to avoid.
    """
    code = _terraform_code()
    assert "moved {" in code, (
        "the legacy invoker was renamed with no moved block. Terraform would destroy the live "
        "binding and create a new one, and the serving revision loses Synapse access in between."
    )
    moved = re.search(r"moved\s*\{(.*?)\n\}", code, re.DOTALL)
    assert moved is not None
    assert "frontend_invoker" in moved.group(1) and "legacy_default_compute_invoker" in moved.group(1), (
        "the moved block does not map the old invoker address to the legacy one"
    )
