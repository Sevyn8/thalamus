"""The cm-backend Terraform module's IAM shape, checked rather than asserted in a comment.

WHY THIS FILE EXISTS NOW. The module gained its first custom IAM role in the channels slice
(cmChannelVaultWriter, granting cm-backend-sa create/get/add/list/destroy on the per-tenant
channel credential secrets). A module gaining its first IAM resource is the cheapest moment to
assert its shape: there is exactly one thing to describe, and the description is still true.

WHAT IT IS ACTUALLY GUARDING. One permission, by its absence: secretmanager.versions.access.
CM writes a tenant's channel credential and never reads it back. That is a promise the surface
makes to the tenant, and the ONLY thing that makes it structural rather than a convention is
that the role cannot do it. channels/secret_writer.py has no read method, but a read method is
one commit away; the role is what makes adding one useless. Note that this diverges from
tokenVaultWriter in cloud-run-service-dis-ui-server, which DOES hold versions.access. So the
absence here cannot be maintained by copying the neighbouring module, and a reviewer reaching for
that module as the pattern would reintroduce it. Hence a test.

AND THE OTHER HALF OF THE SAME MECHANISM. The role lets cm-backend create those secrets; it does
not make it try. main.py:140 constructs the writer only when CHANNELS_SECRETS_PROJECT_ID is set,
and config.py:147 defaults it to None. A module with a perfect role and no such variable applies
cleanly and produces a service whose channels write refuses with CHANNELS_UNAVAILABLE, which is a
privilege granted ahead of its caller wearing the costume of a correct apply. So this file
asserts the variable too, and asserts its VALUE against the project the role is scoped to, since
two halves that each look right and name different projects meet nowhere.

BOTH DIRECTIONS, ALWAYS. The permission set is asserted as exact set equality, not as a subset.
A one-directional check goes stale silently: a REMOVED permission fails loudly at runtime the
next time somebody saves a channel, but an ADDED one fails nothing at all and the check keeps
passing while asserting less than its own docstring claims. This estate has already paid for that
shape twice on synapse-ui-server, in a file whose comment forbade exactly the drift that
happened. Modelled on synapse/services/synapse-ui-server/tests/test_deployment_posture.py.
"""

from __future__ import annotations

import re
from pathlib import Path

# cm-backend/tests/unit/ -> repo root
_REPO_ROOT = Path(__file__).resolve().parents[3]
_MODULE = _REPO_ROOT / "infra" / "modules" / "cloud-run-service-cm" / "main.tf"
_SECRET_WRITER = _REPO_ROOT / "cm-backend" / "src" / "admin_backend" / "channels" / "secret_writer.py"

_ROLE_RESOURCE = "channel_vault_writer"

# The decided set, written out here so the test states the contract rather than reading it back
# from the file it is checking.
_EXPECTED_PERMISSIONS = frozenset(
    {
        "secretmanager.secrets.create",
        "secretmanager.secrets.get",
        "secretmanager.versions.add",
        "secretmanager.versions.list",
        "secretmanager.versions.destroy",
    }
)

_FORBIDDEN_PERMISSION = "secretmanager.versions.access"


def _terraform_code() -> str:
    """The module with comments removed, leaving only what terraform acts on.

    The comments MUST go. The header explains at length why versions.access is absent, and names
    it to do so, so a scan of the raw file would flag the very prose that documents the decision.
    Same trap synapse-ui-server's equivalent hit with allUsers, and the same fix.
    """
    source = _MODULE.read_text(encoding="utf-8")
    # Heredocs first: their bodies can contain anything, including '#'.
    source = re.sub(r"<<-?(\w+)\n.*?^\s*\1\b", "", source, flags=re.DOTALL | re.MULTILINE)
    return "\n".join(
        line for line in source.splitlines() if not line.strip().startswith(("#", "//"))
    )


def _balanced_block(source: str, header: str) -> str:
    """The body of the first block whose opening line matches ``header``, braces balanced."""
    match = re.search(re.escape(header) + r"\s*\{", source)
    assert match is not None, f"no block matching {header!r} in {_MODULE}"
    depth = 0
    cursor = match.end() - 1  # at the opening brace
    while cursor < len(source):
        if source[cursor] == "{":
            depth += 1
        elif source[cursor] == "}":
            depth -= 1
            if depth == 0:
                return source[match.end() : cursor]
        cursor += 1
    raise AssertionError(f"unbalanced braces after {header!r} in {_MODULE}")


def test_the_terraform_module_is_where_this_test_thinks_it_is() -> None:
    """THE VACUITY GUARD, and it is not ceremony.

    Every check below reads one file. If the module is moved or renamed, a path that no longer
    resolves would make all of them pass against an empty string: the "0 == 0 proves nothing"
    failure this project has already paid for. Absence is a failure here, not a pass.
    """
    assert _MODULE.is_file(), (
        f"{_MODULE} not found. If the module moved, update _MODULE. Do not delete these tests; "
        "they are what keeps cm-backend's vault role unable to read a tenant's credential."
    )
    source = _MODULE.read_text(encoding="utf-8")
    # And that it is the RIGHT file, not merely a file.
    assert "google_cloud_run_v2_service" in source
    assert f'"google_project_iam_custom_role" "{_ROLE_RESOURCE}"' in source


def test_the_channel_vault_role_grants_exactly_the_decided_permissions() -> None:
    """Set equality, BOTH DIRECTIONS. See the module docstring for why a subset check rots."""
    block = _balanced_block(
        _terraform_code(), f'resource "google_project_iam_custom_role" "{_ROLE_RESOURCE}"'
    )
    permissions = set(re.findall(r'"(secretmanager\.[a-z.]+)"', block))
    assert permissions, "parsed zero permissions; the regex has stopped biting"

    missing = _EXPECTED_PERMISSIONS - permissions
    added = permissions - _EXPECTED_PERMISSIONS
    assert not missing, (
        f"cmChannelVaultWriter no longer grants {sorted(missing)}. If secretmanager.versions.list "
        "or .destroy went, ChannelSecretWriter.prune now fails with PermissionDenied and the call "
        "site swallows it, so superseded credentials accumulate live and silently."
    )
    assert not added, (
        f"cmChannelVaultWriter has gained {sorted(added)}, which nothing decided. Every permission "
        "in this role has a named caller; add the caller and the reasoning to the module comment "
        "in the same commit, or do not add the permission."
    )


def test_the_role_cannot_read_a_credential_back() -> None:
    """THE ONE THAT MATTERS, and it is scoped to the whole module, not just the role block.

    Anywhere in this module, in any role or any predefined binding, is a way to hand cm-backend
    the ability to read a tenant's credential back. The check is deliberately broader than the
    resource the decision was made about.
    """
    assert _FORBIDDEN_PERMISSION not in _terraform_code(), (
        f"{_FORBIDDEN_PERMISSION} has appeared in cloud-run-service-cm. CM writes a tenant's "
        "channel credential and never reads it back; the form cannot pre-fill and states that "
        "saving replaces the credential. That promise is enforced by this permission's absence "
        "and by nothing else. tokenVaultWriter in cloud-run-service-dis-ui-server DOES hold it, "
        "so copying that module is how this gets reintroduced. The eventual reader of these "
        "secrets is the axon-sender adapter, under its own role on its own service account."
    )


def test_no_broad_predefined_secret_manager_role_is_granted() -> None:
    """The narrow custom role is pointless if a predefined role sits beside it granting the lot."""
    code = _terraform_code()
    for role in ("roles/secretmanager.admin", "roles/secretmanager.secretVersionManager"):
        assert role not in code, (
            f"{role} is granted in cloud-run-service-cm. It subsumes cmChannelVaultWriter and "
            "includes secretmanager.versions.access, which defeats the whole arrangement."
        )


def test_the_binding_references_the_custom_role_and_the_modules_own_identity() -> None:
    """A correct role bound to the wrong principal, or a stale role_id string, plans clean."""
    block = _balanced_block(
        _terraform_code(), f'resource "google_project_iam_member" "{_ROLE_RESOURCE}"'
    )
    assert f"google_project_iam_custom_role.{_ROLE_RESOURCE}.id" in block, (
        "the binding does not reference the custom role by .id. A hardcoded role string does not "
        "create a dependency edge, so the binding can apply before the role exists."
    )
    assert "google_service_account.cm_backend.email" in block, (
        "the binding does not name this module's own runtime service account."
    )


def test_the_service_is_told_which_project_to_write_channel_secrets_in() -> None:
    """THE OTHER HALF OF THE MECHANISM, and without it every test above asserts half of one.

    The role lets cm-backend create the per-tenant channel secrets. It does not make it try.
    main.py:140 constructs the ChannelSecretWriter only when channels_secrets_project_id is set,
    and config.py:147 defaults it to None, so a module carrying a perfect role and no
    CHANNELS_SECRETS_PROJECT_ID produces a service where PUT /api/v1/channels refuses with
    CHANNELS_UNAVAILABLE at channels.py:149. That is a privilege granted ahead of its caller
    wearing the costume of a correct apply.

    THE VALUE IS ASSERTED, NOT JUST THE PRESENCE, and that is the load-bearing half. The custom
    role is a PROJECT-level role in var.project_id bound to this service's own SA, so it reaches
    secrets in that project and nowhere else. An env var naming any other project would construct
    a writer that fails PermissionDenied on its first save: two halves that each look right and
    do not meet. Asserting both name the same expression is what makes them one mechanism.
    """
    code = _terraform_code()
    match = re.search(r"^\s*CHANNELS_SECRETS_PROJECT_ID\s*=\s*(\S+)\s*$", code, flags=re.MULTILINE)
    assert match is not None, (
        "CHANNELS_SECRETS_PROJECT_ID is not set on the cm-backend service. Without it "
        "main.py:140 never constructs the ChannelSecretWriter, so cmChannelVaultWriter is a role "
        "granted to a code path that cannot run."
    )
    assert match.group(1) == "var.project_id", (
        f"CHANNELS_SECRETS_PROJECT_ID is set to {match.group(1)}, not var.project_id. The custom "
        "role is project-scoped to var.project_id, so it cannot reach secrets anywhere else and "
        "the first save would fail with PermissionDenied. If channel secrets genuinely moved "
        "project, the role and its binding move with them, and this test changes with both."
    )

    role_block = _balanced_block(
        code, f'resource "google_project_iam_custom_role" "{_ROLE_RESOURCE}"'
    )
    assert re.search(r"^\s*project\s*=\s*var\.project_id\s*$", role_block, flags=re.MULTILINE), (
        "the custom role is no longer scoped to var.project_id, so the assertion above is "
        "comparing the env var against a project the role does not cover."
    )


def test_the_prune_permissions_still_have_their_caller() -> None:
    """versions.list and .destroy are justified by one method. If it goes, so does the grant.

    This is the half of "granted ahead of its caller" that a Terraform-only test cannot see. The
    grant is defensible today because ChannelSecretWriter.prune calls both. A refactor that drops
    the prune leaves two permissions in the role that nothing uses, and nothing else would notice.
    """
    assert _SECRET_WRITER.is_file(), f"{_SECRET_WRITER} not found; update the path"
    source = _SECRET_WRITER.read_text(encoding="utf-8")
    assert "def prune(" in source, (
        "ChannelSecretWriter.prune is gone. It is the only caller of secretmanager.versions.list "
        "and .destroy; drop those two permissions from cmChannelVaultWriter in the same commit."
    )
    assert "list_secret_versions" in source and "destroy_secret_version" in source, (
        "ChannelSecretWriter.prune no longer lists or destroys versions, so cmChannelVaultWriter "
        "grants permissions with no caller."
    )
