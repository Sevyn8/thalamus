"""Auth0 provisioning service (Slice 2c, per D-39).

Composes the Auth0ManagementClient into DB-first, idempotent get-or-create
against COMMITTED CM rows. This module writes NOTHING to the CM DB: it takes
primitives already read from the committed row (under RLS/PLATFORM context by
the caller) and calls Auth0 only. Persisting auth0_sub / invited_at / status is
Slice 2d's job.

Idempotency (D-39): natural-key lookup-before-create. The Organization is keyed
by a deterministic name derived from the CM tenant_id; the user by email.

Invitation-send and accept are out of scope here (2d); this does create org +
user + membership + app_metadata only.
"""
from __future__ import annotations

import re
from uuid import UUID

from admin_backend.auth.auth0_management import (
    Auth0ManagementClientProtocol,
    Organization,
)
from admin_backend.errors import Auth0ManagementError
from admin_backend.schemas.provisioning import (
    TenantOrgProvisionResult,
    TenantUserProvisionResult,
)

# Auth0 Organization name rule (per the 2b grounding): lowercase, ^[a-z0-9-_]+$,
# 3-50 chars. A UUID lowercased is [0-9a-f-]; "tenant-<uuid>" is 43 chars and
# satisfies the rule.
_ORG_NAME_RE = re.compile(r"^[a-z0-9-_]{3,50}$")


def org_name_for_tenant(tenant_id: UUID) -> str:
    """Deterministic Auth0 Organization name for a CM tenant (D-39 natural key).

    Stable across retries, so the get-before-create lookup is idempotent.
    """
    name = f"tenant-{tenant_id}"
    if not _ORG_NAME_RE.match(name):  # pragma: no cover - a UUID always matches
        raise Auth0ManagementError(
            f"Derived Auth0 org name {name!r} violates Auth0's naming rule",
            operation="org_name",
        )
    return name


async def _get_or_create_org(
    mgmt: Auth0ManagementClientProtocol,
    *,
    tenant_id: UUID,
    tenant_name: str,
    display_code: str | None,
) -> tuple[Organization, bool]:
    """Return ``(org, created)`` for the tenant, creating it only if absent.

    Handles the create-vs-create race: if a concurrent caller created the org
    between the get and our create, re-read it rather than surfacing a conflict.
    """
    name = org_name_for_tenant(tenant_id)
    existing = await mgmt.get_organization_by_name(name)
    if existing is not None:
        return existing, False
    display_name = display_code if display_code else tenant_name
    try:
        created = await mgmt.create_organization(name=name, display_name=display_name)
        return created, True
    except Auth0ManagementError:
        # Possible get/create race: re-read once; return it if it now exists.
        raced = await mgmt.get_organization_by_name(name)
        if raced is not None:
            return raced, False
        raise


async def provision_tenant_organization(
    mgmt: Auth0ManagementClientProtocol,
    *,
    tenant_id: UUID,
    tenant_name: str,
    display_code: str | None,
) -> TenantOrgProvisionResult:
    """Get-or-create the Auth0 Organization for a committed tenant row."""
    org, created = await _get_or_create_org(
        mgmt, tenant_id=tenant_id, tenant_name=tenant_name, display_code=display_code
    )
    return TenantOrgProvisionResult(
        tenant_id=tenant_id, org_id=org.id, org_name=org.name, created=created
    )


async def provision_tenant_user(
    mgmt: Auth0ManagementClientProtocol,
    *,
    connection: str,
    tenant_id: UUID,
    cm_user_id: UUID,
    email: str,
    tenant_name: str,
    display_code: str | None,
) -> TenantUserProvisionResult:
    """Get-or-create the Auth0 user for a committed tenant_users row, add it to
    the tenant Organization, and stamp app_metadata.

    app_metadata carries exactly the keys the cortex-cm-claims Action reads
    (tenant_id, user_type, cm_user_id); NOT email (the Action sources email from
    the Auth0 profile, which create_user sets), and cm_user_id NOT user_id (the
    Action maps cm_user_id -> the .../user_id claim).
    """
    # Defensive get-or-create of the Org (it should already exist from the
    # tenant provision, but this action must not depend on call ordering).
    org, _ = await _get_or_create_org(
        mgmt, tenant_id=tenant_id, tenant_name=tenant_name, display_code=display_code
    )

    app_metadata: dict[str, object] = {
        "tenant_id": str(tenant_id),
        "user_type": "TENANT",
        "cm_user_id": str(cm_user_id),
    }

    existing_user = await mgmt.get_user_by_email(email)
    if existing_user is None:
        user = await mgmt.create_user(
            email=email,
            connection=connection,
            app_metadata=app_metadata,
            email_verified=False,
        )
        user_created = True
    else:
        # Ensure the claims are present/current on the already-existing user.
        user = await mgmt.update_user_app_metadata(
            user_id=existing_user.user_id, app_metadata=app_metadata
        )
        user_created = False

    # Auth0's add-members is idempotent (204 even if already a member), so this
    # is safe to call on every provision.
    await mgmt.add_organization_member(org_id=org.id, user_id=user.user_id)

    return TenantUserProvisionResult(
        user_id=cm_user_id,
        tenant_id=tenant_id,
        org_id=org.id,
        auth0_user_id=user.user_id,
        user_created=user_created,
    )
