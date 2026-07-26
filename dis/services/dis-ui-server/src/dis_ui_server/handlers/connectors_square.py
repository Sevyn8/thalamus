"""Square OAuth connect endpoints (S2): authorize-url + complete.

Flow (Option A, SPA-mediated): the SPA calls ``authorize-url`` (authenticated), redirects the
seller to the returned Square URL, Square redirects the browser back to the SPA callback
route, and the SPA POSTs the ``code`` + ``state`` to ``complete`` (authenticated). ``complete``
validates the signed state, exchanges the code for tokens, and writes them to the Secret
Manager vault keyed by (tenant, source). No token or secret is ever logged or returned.

Both endpoints are authenticated via the normal Bearer seam (``require_write_scope``): the
tenant comes from the verified token, and the state's tenant is cross-checked against it.
The OAuth client / vault / state key are built once in the lifespan and read off
``app.state``; when the server has no OAuth config they are ``None`` and both endpoints fail
loud with 503 (the rest of the BFF is unaffected).
"""

from __future__ import annotations

import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID

import anyio.to_thread
from fastapi import APIRouter, Depends, Query, Request

from dis_core.errors import OpsRoleRequiredError
from dis_ui_server.auth.identity import UserType
from dis_ui_server.auth.scope import WriteScope, require_write_scope, resolve_acted_for
from dis_ui_server.oauth.errors import (
    OauthNotConfiguredError,
    OauthStateTenantMismatchError,
    SquareTokenExchangeError,
)
from dis_ui_server.oauth.state import sign_state, verify_state
from dis_ui_server.schemas.connectors_square import (
    AuthorizeUrlResponse,
    OAuthCompleteRequest,
    OAuthCompleteResponse,
)
from thalamus_square_oauth import SquareOAuthClient, SquareOAuthError, SquareTokenVault

router = APIRouter()

# The signed state is short-lived: long enough for a seller to complete the Square consent
# screen, short enough to bound replay (the code is single-use at Square regardless).
_STATE_TTL = timedelta(minutes=10)


def _require_oauth(request: Request) -> tuple[SquareOAuthClient, SquareTokenVault, str]:
    """The lifespan-built OAuth dependencies, or 503 when the server has no OAuth config."""
    client: SquareOAuthClient | None = request.app.state.square_oauth_client
    vault: SquareTokenVault | None = request.app.state.square_token_vault
    key: str | None = request.app.state.square_oauth_state_key
    if client is None or vault is None or key is None:
        raise OauthNotConfiguredError(
            "Square OAuth is not configured on this server", connector="square"
        )
    return client, vault, key


def _assert_caller_may_act_for(write_scope: WriteScope, tenant_id: UUID) -> None:
    """A TENANT caller may act only for its own tenant; a PLATFORM caller needs dis:ops."""
    if write_scope.user_type is UserType.TENANT:
        if write_scope.token_tenant != tenant_id:
            # Never echo the mismatched tenant id.
            raise OauthStateTenantMismatchError("the OAuth state tenant does not match the caller")
    elif not write_scope.has_ops:
        raise OpsRoleRequiredError("dis:ops role required for a PLATFORM connect")


@router.get("/connectors/square/oauth/authorize-url")
async def square_oauth_authorize_url(
    request: Request,
    write_scope: Annotated[WriteScope, Depends(require_write_scope)],
    source_id: Annotated[str, Query(min_length=1, max_length=128)],
    acting_for_tenant_id: Annotated[UUID | None, Query()] = None,
) -> AuthorizeUrlResponse:
    """Build the Square authorization URL + a signed state bound to (tenant, source).

    The acted-for tenant is resolved from the verified token: TENANT pins its own (a named
    acting_for is 403); PLATFORM + dis:ops uses the named acting_for.
    """
    client, _vault, key = _require_oauth(request)
    acted_for = resolve_acted_for(write_scope, acting_for_tenant_id)
    state = sign_state(
        tenant_id=acted_for,
        source_id=source_id,
        key=key,
        nonce=secrets.token_urlsafe(16),
        now=datetime.now(UTC),
        ttl=_STATE_TTL,
    )
    return AuthorizeUrlResponse(authorize_url=client.authorize_url(state=state), state=state)


@router.post("/connectors/square/oauth/complete")
async def square_oauth_complete(
    request: Request,
    write_scope: Annotated[WriteScope, Depends(require_write_scope)],
    body: OAuthCompleteRequest,
) -> OAuthCompleteResponse:
    """Validate the state, exchange the code, and persist the token set in the vault.

    The state (minted by authorize-url) is the authority for which (tenant, source) the
    tokens belong to; the caller must be allowed to act for that tenant.
    """
    client, vault, key = _require_oauth(request)
    state = verify_state(body.state, key=key)
    _assert_caller_may_act_for(write_scope, state.tenant_id)
    # Blocking httpx + Secret Manager calls run off the event loop (async-service pattern).
    try:
        token_set = await anyio.to_thread.run_sync(client.exchange_code, body.code)
    except SquareOAuthError as exc:
        # No vendor detail crosses into the client response (kept out of the error).
        raise SquareTokenExchangeError("the Square authorization code exchange failed") from exc
    await anyio.to_thread.run_sync(vault.write, state.tenant_id, state.source_id, token_set)
    return OAuthCompleteResponse(
        connector="square",
        status="connected",
        source_id=state.source_id,
        merchant_id=token_set.merchant_id,
    )
