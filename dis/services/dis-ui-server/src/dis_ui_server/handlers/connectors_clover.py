"""Clover OAuth connect endpoints (C3): authorize-url + complete.

Flow (SPA-mediated, exactly as Square's and for the same reason - Cloud Run is
authenticated-only): the SPA calls ``authorize-url`` (authenticated), redirects the merchant
to the returned Clover URL, Clover redirects the browser back to the SPA launch route, and
the SPA POSTs the ``code`` + ``state`` + ``merchant_id`` to ``complete`` (authenticated).
``complete`` validates the signed state, exchanges the code, and writes the token record to
the Secret Manager vault keyed by (tenant, source). No token or secret is ever logged or
returned.

DUPLICATED FROM connectors_square.py, DELIBERATELY (D5). No /connectors/{vendor}/... route
with a vendor registry, because Square and Clover OAuth genuinely differ and a shared
handler would have to hide that. The differences are real and visible below:

  - Clover's TOKEN RESPONSE CARRIES NO MERCHANT ID. It arrives on the callback query string
    instead, so `complete` takes it from the request body and stamps it onto the record.
    Square's falls out of the exchange.
  - Clover's exchange is JSON-ONLY (form-encoded is a 415) and its refresh leg takes no
    client secret. Both live in thalamus-clover-oauth, which this handler consumes whole.
  - The record Clover stores is a CloverTokenSet with UNIX-timestamp expiries and a
    previous_refresh_token, because Clover refresh tokens are single-use.

Two implementations is data; three is when to extract.

The STATE MECHANISM is shared, and that is not a contradiction: oauth/state.py is
vendor-agnostic, Clover echoes `state` back verbatim (confirmed), and the key is now
published unconditionally as ``app.state.oauth_state_key`` rather than inside a vendor
branch. Same claim shape, same tenant-mismatch rejection, one secret.
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
    CloverTokenExchangeError,
    OauthNotConfiguredError,
    OauthStateTenantMismatchError,
)
from dis_ui_server.oauth.state import sign_state, verify_state
from dis_ui_server.schemas.connectors_clover import (
    AuthorizeUrlResponse,
    OAuthCompleteRequest,
    OAuthCompleteResponse,
)
from thalamus_clover_oauth import CloverOAuthClient, CloverOAuthError, CloverTokenVault

router = APIRouter()

# The signed state is short-lived: long enough for a merchant to complete the Clover consent
# screen, short enough to bound replay (the code is single-use at Clover regardless).
_STATE_TTL = timedelta(minutes=10)


def _require_oauth(request: Request) -> tuple[CloverOAuthClient, CloverTokenVault, str]:
    """The lifespan-built OAuth dependencies, or 503 when the server has no Clover config.

    The state key is read from the SHARED, unconditionally-published attribute, not from a
    vendor one: an unconfigured Square must never be able to take Clover's connect down.
    """
    client: CloverOAuthClient | None = request.app.state.clover_oauth_client
    vault: CloverTokenVault | None = request.app.state.clover_token_vault
    key: str | None = request.app.state.oauth_state_key
    if client is None or vault is None or key is None:
        raise OauthNotConfiguredError("Clover OAuth is not configured on this server", connector="clover")
    return client, vault, key


def _assert_caller_may_act_for(write_scope: WriteScope, tenant_id: UUID) -> None:
    """A TENANT caller may act only for its own tenant; a PLATFORM caller needs dis:ops."""
    if write_scope.user_type is UserType.TENANT:
        if write_scope.token_tenant != tenant_id:
            # Never echo the mismatched tenant id.
            raise OauthStateTenantMismatchError("the OAuth state tenant does not match the caller")
    elif not write_scope.has_ops:
        raise OpsRoleRequiredError("dis:ops role required for a PLATFORM connect")


@router.get("/connectors/clover/oauth/authorize-url")
async def clover_oauth_authorize_url(
    request: Request,
    write_scope: Annotated[WriteScope, Depends(require_write_scope)],
    source_id: Annotated[str, Query(min_length=1, max_length=128)],
    acting_for_tenant_id: Annotated[UUID | None, Query()] = None,
) -> AuthorizeUrlResponse:
    """Build the Clover authorization URL + a signed state bound to (tenant, source).

    Self-serve TENANT is the primary path: the tenant is pinned from the verified token and
    a named acting_for is a 403. PLATFORM + dis:ops uses the named acting_for, so the
    ops-connects-a-client journey stays available.
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


@router.post("/connectors/clover/oauth/complete")
async def clover_oauth_complete(
    request: Request,
    write_scope: Annotated[WriteScope, Depends(require_write_scope)],
    body: OAuthCompleteRequest,
) -> OAuthCompleteResponse:
    """Validate the state, exchange the code, and persist the token record in the vault.

    The state (minted by authorize-url) is the authority for which (tenant, source) the
    tokens belong to; the caller must be allowed to act for that tenant. The merchant comes
    from the request body because Clover's token response does not carry one.
    """
    client, vault, key = _require_oauth(request)
    state = verify_state(body.state, key=key)
    _assert_caller_may_act_for(write_scope, state.tenant_id)
    # Blocking httpx + Secret Manager calls run off the event loop (async-service pattern).
    try:
        token_set = await anyio.to_thread.run_sync(
            lambda: client.exchange_code(
                body.code, merchant_id=body.merchant_id, employee_id=body.employee_id
            )
        )
    except CloverOAuthError as exc:
        # No vendor detail crosses into the client response (kept out of the error).
        raise CloverTokenExchangeError("the Clover authorization code exchange failed") from exc
    await anyio.to_thread.run_sync(vault.write, state.tenant_id, state.source_id, token_set)
    return OAuthCompleteResponse(
        connector="clover",
        status="connected",
        source_id=state.source_id,
        merchant_id=token_set.merchant_id,
    )
