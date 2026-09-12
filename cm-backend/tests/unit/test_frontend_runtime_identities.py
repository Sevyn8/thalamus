"""cm-frontend and dis-ui-ver2 must each run as their own least-privileged identity.

WHY THIS FILE IS IN cm-backend's SUITE. It asserts Terraform that belongs to two OTHER packages,
which is normally how checks get skipped, so the reason is worth stating. cm-frontend has NO test
runner at all - ``next build`` plus the assert-*.mjs scripts are its entire gate, and those scripts
read files inside cm-frontend only. dis-ui-ver2's runner is vitest, which is the wrong tool for
parsing HCL. cm-backend's unit suite already owns Terraform IAM posture for this plane
(test_deployment_posture.py asserts cloud-run-service-cm's custom role) and it runs on every pull
request. Splitting these across three homes to satisfy ownership would put two of them somewhere
CI does not look. If cm-frontend ever gains a Python suite, move these.

WHAT THIS IS GUARDING. Before P1-IAM-001 both frontends ran as
``<project-number>-compute@developer.gserviceaccount.com`` - the project's default Compute Engine
identity. Two consequences, both structural:

  1. Synapse's invoker binding named that account, so it admitted EVERY default-compute workload
     in the project. "Only cm-frontend may call Synapse" was unenforceable, and the module said so
     rather than pretending otherwise.
  2. dis-ui-ver2 shared an identity holding secretAccessor on both cm-frontend-auth0-* secrets. It
     needs neither, and had silent reach to both purely by sharing the account.

Stage A (P1-IAM-001A) gave each a dedicated identity and deliberately left the legacy grants in
place so the serving revision was never refused before its replacement was ready. Stage B
(P1-IAM-001B) removed them. These tests now assert the FINAL state: the dedicated identities
exist AND the transitional scaffolding is gone.

ONE THING THESE TESTS CANNOT PROVE, AND IT IS NOT AN OVERSIGHT. The two legacy
``secretmanager.secretAccessor`` grants on the cm-frontend-auth0-* secrets were made OUT OF BAND
and Terraform never owned them, so no configuration file records their removal and no static test
can observe it. They are revoked operationally with ``gcloud secrets remove-iam-policy-binding``
after this configuration is applied. A test asserting they are gone would be asserting something
it cannot see, and would pass whether or not the revocation ever happened. Their absence is
verified against the live policy instead, and recorded in the P1-IAM-001B pull request.

ASSERTED AGAINST THE HCL, NOT A PLAN. No credentials are available in CI, so `terraform plan` is
not a gate here. That is a real limit and is stated rather than papered over: these read the
configuration, so they prove what Terraform is ASKED to do. Whether the live project matches is
what the human's plan/apply answers.
"""

from __future__ import annotations

import re
from pathlib import Path

# cm-backend/tests/unit/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_INFRA = _REPO_ROOT / "infra"
_CM_FRONTEND = _INFRA / "modules" / "cloud-run-service-cm-frontend"
_DIS_UI_VER2 = _INFRA / "modules" / "cloud-run-service-dis-ui-ver2"
_SYNAPSE = _INFRA / "modules" / "cloud-run-service-synapse-ui-server"
_STAGING = _INFRA / "envs" / "staging" / "main.tf"

# Any project's default Compute Engine identity, not just this project's number. A migration that
# moved projects and kept the shared-identity habit would otherwise pass.
_DEFAULT_COMPUTE = re.compile(r"\d+-compute@developer\.gserviceaccount\.com")

_REQUIRED_CM_SECRETS = {"auth0_client_secret", "auth0_secret"}


def _code(path: Path) -> str:
    """The file with comments and heredoc bodies removed, leaving what terraform acts on.

    Both must go. These modules discuss the default compute SA at length precisely because they no
    longer use it, so a naive scan of the raw text would flag the explanation of the fix as the
    problem. Same helper shape as synapse-ui-server's posture suite.
    """
    source = path.read_text(encoding="utf-8")
    source = re.sub(r"<<-?(\w+)\n.*?^\s*\1\b", "", source, flags=re.DOTALL | re.MULTILINE)
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith(("#", "//"))
    )


def _service_account_field(path: Path) -> str:
    """The `service_account = ...` assignment inside a Cloud Run template."""
    match = re.search(r"^\s*service_account\s*=\s*(.+)$", _code(path), re.MULTILINE)
    assert match is not None, f"no service_account assignment in {path}"
    return match.group(1).strip()


# --- Vacuity guards. Every assertion below reads a file and matches a pattern. -----------------


def test_the_terraform_modules_are_where_this_test_thinks_they_are() -> None:
    """A move or rename would make every check below pass against nothing."""
    for path in (
        _CM_FRONTEND / "main.tf",
        _CM_FRONTEND / "variables.tf",
        _DIS_UI_VER2 / "main.tf",
        _SYNAPSE / "main.tf",
        _STAGING,
    ):
        assert path.is_file(), (
            f"{path} not found. If infra moved, update the constants - do not delete these tests; "
            "they are what keeps two public frontends off a shared, over-privileged identity."
        )
    assert "google_cloud_run_v2_service" in (_CM_FRONTEND / "main.tf").read_text(encoding="utf-8")
    assert "google_cloud_run_v2_service" in (_DIS_UI_VER2 / "main.tf").read_text(encoding="utf-8")


# --- 1-3: distinct, dedicated runtime identities ----------------------------------------------


def test_cm_frontend_does_not_run_as_a_default_compute_account() -> None:
    field = _service_account_field(_CM_FRONTEND / "main.tf")
    assert not _DEFAULT_COMPUTE.search(field), (
        f"cm-frontend's runtime identity resolves to a default Compute SA: {field}"
    )
    assert field == "var.service_account_email", (
        "cm-frontend's runtime identity is no longer the injected variable. It is supplied by the "
        "staging root because Synapse must name the same account; hardcoding it here is how the "
        "binding and the runtime drift into naming different identities."
    )


def test_cm_frontend_has_no_fallback_to_a_shared_identity() -> None:
    """THE DEFAULT IS THE HOLE. This variable used to default to the default compute SA, so a
    caller that simply omitted it got the shared identity and a clean apply. Removing the default
    turns that omission into a hard error at plan."""
    variables = (_CM_FRONTEND / "variables.tf").read_text(encoding="utf-8")
    block = re.search(r'variable\s+"service_account_email"\s*\{(.*?)\n\}', variables, re.DOTALL)
    assert block is not None, "variable service_account_email is gone from cm-frontend"
    body = block.group(1)
    assert not re.search(r"^\s*default\s*=", body, re.MULTILINE), (
        "cm-frontend's service_account_email has a default again. Any default is a silent "
        "fallback; the one it had was the shared default compute account."
    )
    assert "validation" in body, (
        "the variable lost its validation block, which is what refuses a default-compute address "
        "at plan time regardless of what the root passes."
    )


def test_dis_ui_ver2_runs_as_its_own_dedicated_account() -> None:
    code = _code(_DIS_UI_VER2 / "main.tf")
    assert 'resource "google_service_account" "dis_ui_ver2"' in code, (
        "dis-ui-ver2 creates no service account, so it is back on a shared identity."
    )
    field = _service_account_field(_DIS_UI_VER2 / "main.tf")
    assert not _DEFAULT_COMPUTE.search(field)
    assert field == "google_service_account.dis_ui_ver2.email", (
        f"dis-ui-ver2's runtime identity is not its own account: {field}"
    )


def test_the_two_frontends_do_not_share_a_runtime_identity() -> None:
    """The specific defect P1-IAM-001 names. Sharing made Synapse's invoker binding meaningless
    and gave the DIS UI reach into CM's Auth0 secrets."""
    cm = _service_account_field(_CM_FRONTEND / "main.tf")
    dis = _service_account_field(_DIS_UI_VER2 / "main.tf")
    assert cm != dis, f"both frontends resolve their runtime identity from {cm}"


def test_the_root_passes_distinct_dedicated_accounts() -> None:
    """The modules can only be as separate as the wiring. Asserted at the call site too, because
    two correct modules wired to one account is the same defect with more files."""
    code = _code(_STAGING)
    assert 'resource "google_service_account" "cm_frontend"' in code, (
        "the cm-frontend identity is no longer created at the root. If it moved into the module, "
        "check for a graph cycle: cm-frontend depends on Synapse, and Synapse names this account."
    )
    assert re.search(
        r"service_account_email\s*=\s*google_service_account\.cm_frontend\.email", code
    ), "module.cm_frontend_service is not wired to the dedicated account"
    assert re.search(
        r"caller_service_account_email\s*=\s*google_service_account\.cm_frontend\.email", code
    ), "Synapse's dedicated caller is not wired to the same account cm-frontend runs as"


# --- 4-6: CM secret access, scoped and ordered ------------------------------------------------


def test_cm_frontend_grants_secret_access_on_exactly_its_two_auth0_secrets() -> None:
    """EXACT SET EQUALITY, BOTH DIRECTIONS. A subset check goes stale silently: a removed grant
    fails loudly at the next boot, but an ADDED one fails nothing and this test would keep passing
    while asserting less than it claims."""
    code = _code(_CM_FRONTEND / "main.tf")
    granted = set(
        re.findall(
            r'resource\s+"google_secret_manager_secret_iam_member"\s+"([a-z0-9_]+)"', code
        )
    )
    assert granted == _REQUIRED_CM_SECRETS, (
        f"cm-frontend grants secretAccessor on {sorted(granted)}, expected "
        f"{sorted(_REQUIRED_CM_SECRETS)}. Every secret this identity can read is a credential it "
        "can leak; the set is the permission."
    )
    for role in re.findall(r'role\s*=\s*"(roles/secretmanager[^"]*)"', code):
        assert role == "roles/secretmanager.secretAccessor", (
            f"cm-frontend holds {role} on a secret. secretAccessor reads a version; anything "
            "broader can also change or destroy one."
        )


def test_cm_frontend_secret_grants_are_additive_not_authoritative() -> None:
    """LOAD-BEARING DURING STAGE A, and it looks like a style preference.

    ``_iam_binding`` computes the member list from this file alone and DELETES anyone else. The
    default compute SA holds the same role on both secrets and the currently-serving revision
    reads them with it, so an authoritative binding would black out the live frontend on apply,
    before its replacement revision exists.
    """
    code = _code(_CM_FRONTEND / "main.tf")
    assert "google_secret_manager_secret_iam_binding" not in code, (
        "cm-frontend uses an authoritative secret IAM binding. These secrets were created out "
        "of band and Terraform does not own their policies; an authoritative binding silently "
        "asserts ownership of every member on them."
    )
    assert "google_secret_manager_secret_iam_policy" not in code


def test_the_cm_frontend_revision_is_ordered_after_its_secret_grants() -> None:
    """THE EDGE TERRAFORM WILL NOT INFER, parsed rather than hardcoded so a third secret is
    covered the day it lands.

    The env blocks reference ``data.google_secret_manager_secret.*.secret_id`` - the DATA SOURCE.
    Terraform sees an edge to the data source and none at all to the grant, so it may roll the
    revision onto the new identity before that identity can read either secret. The container
    starts without its Auth0 credentials, the apply is green, and the plan says nothing.
    """
    code = _code(_CM_FRONTEND / "main.tf")
    declared = set(
        re.findall(
            r'resource\s+"google_secret_manager_secret_iam_member"\s+"([a-z0-9_]+)"', code
        )
    )
    assert declared, "parsed zero secret grants; the regex has stopped biting"

    depends = re.search(r"depends_on\s*=\s*\[(.*?)\]", code, re.DOTALL)
    assert depends is not None, (
        "the cm-frontend service has no depends_on. Its secret grants must be listed there or a "
        "revision can roll onto an identity that cannot read its own credentials."
    )
    listed = set(re.findall(r"google_secret_manager_secret_iam_member\.([a-z0-9_]+)", depends.group(1)))
    missing = sorted(declared - listed)
    assert not missing, (
        f"these secret grants are not in the service's depends_on: {missing}."
    )


def test_dis_ui_ver2_is_granted_no_secret_access() -> None:
    """It references no secret and needs none. Sharing cm-frontend's identity had given it access
    to both Auth0 secrets anyway; the dedicated account is only an improvement if it stays bare."""
    code = _code(_DIS_UI_VER2 / "main.tf")
    assert "google_secret_manager_secret_iam" not in code, (
        "dis-ui-ver2 has acquired a Secret Manager grant. It reads no secret; if that changed, "
        "the change belongs in its own review."
    )
    assert "secretmanager" not in code.lower().replace("secretmanager.secretaccessor", ""), (
        "dis-ui-ver2 references Secret Manager in its terraform"
    )


# --- 7-9, 12: Synapse invoker scoping ---------------------------------------------------------


def test_the_synapse_invoker_grant_is_service_scoped() -> None:
    """A project-level roles/run.invoker would let cm-frontend call every Cloud Run service in the
    estate to solve one hop."""
    synapse = _code(_SYNAPSE / "main.tf")
    for path, code in ((_STAGING, _code(_STAGING)), (_SYNAPSE / "main.tf", synapse)):
        assert not re.search(
            r'google_project_iam_(member|binding)[\s\S]{0,400}?roles/run\.invoker', code
        ), f"a PROJECT-level roles/run.invoker appears in {path}"
    assert 'resource "google_cloud_run_v2_service_iam_member" "dedicated_frontend_invoker"' in synapse


def test_dis_ui_ver2_is_not_wired_as_a_synapse_caller() -> None:
    """NEGATIVE GUARD. The two frontends are adjacent in the wiring and the DIS UI has no business
    calling Synapse; granting it invoker "for symmetry" would re-widen exactly what this closes."""
    for path in (_STAGING, _SYNAPSE / "main.tf"):
        code = _code(path)
        for line in code.splitlines():
            if "caller_service_account_email" in line or "run.invoker" in line:
                assert "dis_ui_ver2" not in line, (
                    f"dis-ui-ver2's identity appears on a Synapse caller line in {path}: {line.strip()}"
                )


def test_no_anonymous_invoker_is_introduced_on_synapse() -> None:
    """Unchanged property, re-asserted from this side because this tranche edits that file."""
    for line in _code(_SYNAPSE / "main.tf").splitlines():
        if re.search(r"\bmembers?\s*=", line):
            assert "allUsers" not in line and "allAuthenticatedUsers" not in line, (
                f"synapse-ui-server would be publicly invocable: {line.strip()}"
            )


# --- 10-11, 13: nothing broad, nothing keyed, nothing changed on the public edge ---------------


def test_no_service_account_key_is_created_for_either_identity() -> None:
    """A key is a downloadable, long-lived credential. Cloud Run attaches the identity to the
    revision and the metadata server mints tokens, so neither workload can even use one."""
    for path in (_CM_FRONTEND / "main.tf", _DIS_UI_VER2 / "main.tf", _STAGING):
        assert "google_service_account_key" not in _code(path), (
            f"a service account key resource appears in {path}"
        )


def test_no_project_wide_secret_access_is_introduced() -> None:
    for path in (_CM_FRONTEND / "main.tf", _DIS_UI_VER2 / "main.tf", _STAGING):
        code = _code(path)
        assert not re.search(
            r'google_project_iam_(member|binding)[\s\S]{0,400}?roles/secretmanager', code
        ), f"a PROJECT-level Secret Manager role appears in {path}"


def test_neither_frontend_loses_its_public_invoker_binding() -> None:
    """NOT A GOAL OF THIS TRANCHE, ASSERTED SO IT IS NOT A SIDE EFFECT. Both services are publicly
    callable at the IAM layer. That is a separate standing finding; removing it here would be an
    unreviewed availability change riding on an identity migration."""
    for path in (_CM_FRONTEND / "main.tf", _DIS_UI_VER2 / "main.tf"):
        code = _code(path)
        assert 'resource "google_cloud_run_v2_service_iam_member" "public_invoker"' in code, (
            f"{path} lost its public invoker binding"
        )
        assert re.search(r'member\s*=\s*"allUsers"', code), (
            f"{path}'s public invoker no longer names allUsers"
        )


# --- P1-IAM-001B: the transitional scaffolding is gone ----------------------------------------


def test_no_stage_a_migration_scaffolding_remains_in_terraform() -> None:
    """The overlap constructs existed to survive one cutover and have a removal date.

    Asserted across the staging root and the Synapse module together, because the scaffolding was
    a pair: a variable at the call site and a resource in the module. Removing one and leaving
    the other is the half-done state this catches.
    """
    for path in (_STAGING, _SYNAPSE / "main.tf", _SYNAPSE / "variables.tf"):
        code = _code(path)
        assert "legacy_default_compute_invoker" not in code, (
            f"the legacy default-compute invoker binding is back in {path}"
        )
        assert "legacy_caller_service_account_email" not in code, (
            f"the legacy caller variable is back in {path}"
        )


def test_no_default_compute_address_appears_in_live_terraform() -> None:
    """No literal default-compute principal anywhere in the live configuration, any project.

    The last live reference was the staging root argument that supplied the legacy Synapse
    caller. With it gone the address should not appear in any .tf file the estate applies.
    """
    offenders = []
    for path in sorted(_INFRA.rglob("*.tf")):
        for n, line in enumerate(_code(path).splitlines(), start=1):
            if _DEFAULT_COMPUTE.search(line):
                offenders.append(f"{path.relative_to(_INFRA)}:{n}: {line.strip()}")
    assert offenders == [], (
        f"a default Compute Engine service account is referenced in live terraform: {offenders}"
    )


def test_synapse_has_exactly_one_invoker_and_it_is_the_cm_frontend_account() -> None:
    """The final Synapse posture, asserted from this side too.

    synapse-ui-server's own suite owns this invariant; it is repeated here because this file is
    what a reviewer reads when asking "who can reach what" across the two frontends, and an
    answer that lives only in another package's tests is an answer nobody checks here.
    """
    code = _code(_SYNAPSE / "main.tf")
    bindings = re.findall(
        r'resource\s+"google_cloud_run_v2_service_iam_member"\s+"([a-z0-9_]+)"', code
    )
    assert bindings == ["dedicated_frontend_invoker"], (
        f"expected exactly one Synapse invoker binding, found {bindings}"
    )
    assert "var.caller_service_account_email" in code
