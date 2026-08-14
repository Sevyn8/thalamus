"""Tenant sending channels: the tenant's own configuration, and the operator's fleet view.

Three routes, two audiences, one table.

  GET  /channels           the caller's own tenant's connections.   ADMIN.CHANNELS.VIEW.TENANT
  PUT  /channels           configure or reconfigure one channel.    ADMIN.CHANNELS.CONFIGURE.TENANT
  GET  /channels/platform  every tenant's connection state.         ADMIN.CHANNELS.VIEW.GLOBAL

THE TENANT IS THE SENDER, NEVER SEVYN8. A tenant administrator enters their own provider
credential; Sevyn8 never holds or types another company's. The operator route exists so a blocked
delivery is explicable, and it returns connection STATE and the secret's NAME, never a value.

=================================================================================================
THE GATE IS THE BOUNDARY. /me/permissions IS A HINT.
=================================================================================================
cm-frontend hides the surface using the cached grant set from /me/permissions, and that is a UX
decision made on data the browser already has. It is NOT the access control. Every route below
carries ``Depends(require(...))``, which resolves the caller's grants against the database on
this request, and the write additionally pins its audience. A caller who reaches these URLs
without the grant is refused here regardless of what any client rendered.

=================================================================================================
THE WRITE TOUCHES TWO SYSTEMS THAT CANNOT COMMIT TOGETHER. THE ORDER IS THE MITIGATION.
=================================================================================================
Secret Manager and Postgres have no shared transaction. The order below is D-42's, which governs
the email-change Auth0 sync for the same reason:

  1. Derive the secret's name. Pure, no I/O.
  2. UPSERT the row INTO THE OPEN REQUEST TRANSACTION. Pending, not committed.
  3. Write the secret. The LAST operation before returning.
  4. The dependency commits at teardown.

WHAT EACH FAILURE DOES:

  Vault write fails      the exception escapes the handler, get_tenant_session_dep does not
                         catch it, the transaction rolls back. No row, no secret. The tenant
                         sees an error and retries; nothing is half-configured.

  Commit fails after the secret landed
                         an ORPHAN SECRET and no row. Rare: the row already flushed, so only a
                         connection loss or a deferred-constraint failure can fail the COMMIT.
                         THIS is what the deterministic name is for. The retry derives the SAME
                         name, the create is an AlreadyExists no-op, a version is added and the
                         row lands. With a random name the retry would mint a SECOND secret and
                         the first would hold a live tenant credential that nothing could ever
                         attribute to a tenant or a channel again.

  Row written, no secret CANNOT OCCUR in this order: the row only commits after the vault write
                         returned.

The prune runs after the write and its failure is deliberately NOT fatal: the tenant's credential
is already stored, and losing a successful save because housekeeping failed would be the worse
outcome. It is reported in the response so the surface can say what happened.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from admin_backend.auth.context import AuthContext
from admin_backend.auth.permissions import require
from admin_backend.channels import secret_id_for
from admin_backend.dependencies import get_auth_context, get_tenant_session_dep
from admin_backend.errors import ChannelsUnavailableError
from admin_backend.models.permission import (
    PermissionAction,
    PermissionResource,
    PermissionScope,
)
from admin_backend.models.tenant_module_access import ModuleCode
from admin_backend.repositories.channel_connections import ChannelConnectionsRepo
from admin_backend.schemas.channel import (
    ChannelConnectionRead,
    ChannelConnectionsListResponse,
    ChannelUpsertRequest,
    PlatformChannelConnectionRead,
    PlatformChannelConnectionsListResponse,
)

router = APIRouter(prefix="/channels", tags=["channels"])

_repo = ChannelConnectionsRepo()


@router.get(
    "",
    response_model=ChannelConnectionsListResponse,
    summary="The caller's own tenant's sending channels",
    description=(
        "Connection state for the caller's own tenant. Returns the Secret Manager secret NAME "
        "and never the credential's value; this service cannot read a stored credential back. "
        "RLS scopes the rows to the JWT's tenant."
    ),
)
async def list_my_channels(
    _: None = Depends(
        require(
            ModuleCode.ADMIN,
            PermissionResource.CHANNELS,
            PermissionAction.VIEW,
            PermissionScope.TENANT,
        )
    ),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    rows = await _repo.list_for_session_tenant(session)
    return ChannelConnectionsListResponse(
        items=[ChannelConnectionRead.model_validate(r) for r in rows]
    )


@router.put(
    "",
    response_model=ChannelConnectionRead,
    summary="Configure or reconfigure one sending channel",
    description=(
        "Stores the tenant's own provider credential in Secret Manager and records the "
        "connection. REPLACES the whole credential set: this service cannot read the stored "
        "credential, so there is nothing to merge a partial edit into. Status is server-forced "
        "to `pending`; nothing sends yet."
    ),
)
async def upsert_my_channel(
    payload: ChannelUpsertRequest,
    request: Request,
    _: None = Depends(
        require(
            ModuleCode.ADMIN,
            PermissionResource.CHANNELS,
            PermissionAction.CONFIGURE,
            PermissionScope.TENANT,
            audience="TENANT",
        )
    ),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    """See the module docstring for the ordering and both failure directions.

    ``audience="TENANT"`` REFUSES A PLATFORM CALLER, and that is the standing rule rather than a
    permission detail: Sevyn8 never types another company's credential. The row's own policy
    would refuse a PLATFORM write anyway (WITH CHECK has no PLATFORM branch), but a refusal at
    the gate names the reason instead of surfacing as a policy violation.
    """
    writer = getattr(request.app.state, "channel_secret_writer", None)
    if writer is None:
        raise ChannelsUnavailableError(
            internal_message=(
                "channel upsert requested but CHANNELS_SECRETS_PROJECT_ID is unset, so no "
                "ChannelSecretWriter was constructed"
            ),
            channel=payload.channel,
        )

    # auth.tenant_id is non-null for TENANT callers by AuthContext's own validator, and the
    # audience gate above has already refused everyone else.
    assert auth.tenant_id is not None
    secret_ref = secret_id_for(auth.tenant_id, payload.channel)

    # 1. The row, into the open transaction. Not committed here.
    row = await _repo.upsert(
        session,
        tenant_id=auth.tenant_id,
        channel=payload.channel,
        provider=payload.provider,
        sending_identity=payload.sending_identity,
        secret_ref=secret_ref,
    )

    # 2. The vault, last before returning. A failure here rolls the row back.
    version_name = writer.write(secret_ref, payload.credential_blob())

    # 3. Housekeeping. Deliberately not fatal: the credential is stored and a failed prune must
    #    not lose the tenant a successful save. It IS reported, because a prune that silently
    #    does nothing is indistinguishable from one that works.
    try:
        writer.prune(secret_ref, version_name)
    except Exception:  # noqa: BLE001 - see above; the credential is already safely stored
        pass

    return ChannelConnectionRead.model_validate(row)


@router.get(
    "/platform",
    response_model=PlatformChannelConnectionsListResponse,
    summary="Every tenant's channel connection state",
    description=(
        "Which tenants have which channels configured, across the fleet. Returns connection "
        "state and the Secret Manager secret NAME; never a credential value. Exists so a "
        "blocked or suppressed delivery is explicable."
    ),
)
async def list_platform_channels(
    _: None = Depends(
        require(
            ModuleCode.ADMIN,
            PermissionResource.CHANNELS,
            PermissionAction.VIEW,
            PermissionScope.GLOBAL,
            audience="PLATFORM",
        )
    ),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    """SESSION POSTURE: PLATFORM, and it is load-bearing rather than incidental.

    The table is FORCE RLS and the PLATFORM branch lives in USING only, so this query returns
    every tenant's row under a PLATFORM session and ZERO ROWS, silently, under any other. The
    ``audience="PLATFORM"`` gate is what makes the posture and the permission agree: without it a
    TENANT caller holding a GLOBAL grant would reach this handler and receive their own single
    row, which reads as "only one tenant has configured anything".
    """
    rows = await _repo.list_all_tenants(session)
    return PlatformChannelConnectionsListResponse(
        items=[PlatformChannelConnectionRead.model_validate(r) for r in rows]
    )
