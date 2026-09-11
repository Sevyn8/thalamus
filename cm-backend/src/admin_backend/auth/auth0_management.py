"""Auth0ManagementClient: thin M2M client for the Auth0 Management API v2.

A small seam over ``httpx`` for the Management operations that tenant /
tenant-user provisioning composes into (D-39). This module does NOT wire into
any handler and does NOT hit the live Auth0 tenant at construction;
provisioning hooks are added by the caller.

Auth: client-credentials (M2M) grant against the Management audience using the
"Cortex CM Backend M2M" app. The access token is cached in-memory and refreshed
on expiry (mirrors the AuthClient posture). Every token / HTTP /
parse failure maps to a typed ``Auth0ManagementError`` (a ServerError), never a
raw unhandled 500, per D-39.

Idempotency (D-39) is intentionally NOT baked in here: this client exposes
plain ``create_*`` and ``get_*`` methods and lets the caller compose the
natural-key get-or-create (Organization by deterministic name, user by
email), keeping the client thin.

Seam: the client is fake-injectable two ways. For the client's own offline
tests, an ``httpx.AsyncClient`` (backed by ``httpx.MockTransport``) is injected
so the real request-building / response-parsing runs without a network. For
callers and their tests, ``Auth0ManagementClientProtocol`` lets a fake stand
in for the whole client (mirrors the ``AuthClient`` Protocol).

Not a guess: ``create_user`` takes ``connection`` as a parameter rather than
hardcoding a connection name; the database-connection name is tenant Auth0
config, resolved by the caller (likely a future setting), not assumed here.
"""
from __future__ import annotations

import asyncio
import secrets
import string
import time
from typing import Any, Protocol, runtime_checkable

import httpx
from pydantic import BaseModel, ConfigDict

from admin_backend.config import Settings
from admin_backend.errors import Auth0ManagementError

# Refresh the M2M token this many seconds BEFORE its stated expiry, so an
# in-flight call never races the boundary.
_TOKEN_SKEW_SECONDS = 60
# Per-request timeout for Management calls.
_HTTP_TIMEOUT_SECONDS = 10.0

# Bound on the Auth0 error-body excerpt attached to Auth0ManagementError so a
# 4xx names itself without archaeology. Never includes the request body.
_ERROR_BODY_EXCERPT_LIMIT = 300

# Auth0 Database connections require a password on POST /users. CM creates the
# user with a throwaway password satisfying Auth0's default policy; the user
# never learns it and sets their own via the password-change ticket. The
# special set is a conservative subset Auth0 accepts.
_PASSWORD_SPECIALS = "!@#$%^&*()-_=+"
_PASSWORD_LENGTH = 28  # >= 24 with margin


def _generate_initial_password() -> str:
    """Return a cryptographically random single-use password that
    deterministically satisfies Auth0's default policy (length >= 24 and at
    least one each of upper, lower, digit, special).

    Not left to ``token_urlsafe`` luck: one character from each required
    class is seeded explicitly, the remainder drawn from the combined pool,
    then shuffled with a CSPRNG-backed shuffler. Never stored, logged, or
    returned to any caller: the user sets their own password via the
    password-change ticket.
    """
    pools = (
        string.ascii_uppercase,
        string.ascii_lowercase,
        string.digits,
        _PASSWORD_SPECIALS,
    )
    combined = "".join(pools)
    chars = [secrets.choice(pool) for pool in pools]
    chars += [
        secrets.choice(combined)
        for _ in range(_PASSWORD_LENGTH - len(pools))
    ]
    secrets.SystemRandom().shuffle(chars)
    return "".join(chars)


def _error_body_excerpt(resp: httpx.Response) -> str:
    """Bounded, log-safe excerpt of an Auth0 error RESPONSE body.

    Prefers the JSON ``message`` field (Auth0's human-readable reason);
    falls back to the raw text. Truncated to ``_ERROR_BODY_EXCERPT_LIMIT``.
    Operates on the RESPONSE only, never the request body (which may carry
    the create-user password).
    """
    excerpt: str
    try:
        data = resp.json()
        message = data.get("message") if isinstance(data, dict) else None
        excerpt = message if isinstance(message, str) else resp.text
    except (ValueError, UnicodeDecodeError):
        excerpt = resp.text
    return excerpt[:_ERROR_BODY_EXCERPT_LIMIT]


class Organization(BaseModel):
    """An Auth0 Organization, projected to the fields CM uses. Extra Auth0
    fields (branding, metadata, etc.) are ignored."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    id: str
    name: str
    display_name: str | None = None


class Auth0User(BaseModel):
    """An Auth0 user, projected to the fields CM uses. ``user_id`` is the
    Auth0 ``sub`` that CM stores as ``auth0_sub``."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    user_id: str
    email: str | None = None


@runtime_checkable
class Auth0ManagementClientProtocol(Protocol):
    """The Management operations that provisioning depends on. Callers and
    their tests inject a fake satisfying this Protocol; mypy --strict covers
    the substitution."""

    async def create_organization(self, *, name: str, display_name: str) -> Organization: ...

    async def get_organization_by_name(self, name: str) -> Organization | None: ...

    async def create_user(
        self,
        *,
        email: str,
        connection: str,
        app_metadata: dict[str, Any] | None = None,
        email_verified: bool = False,
    ) -> Auth0User: ...

    async def get_user_by_email(self, email: str) -> Auth0User | None: ...

    async def add_organization_member(self, *, org_id: str, user_id: str) -> None: ...

    async def update_user_app_metadata(
        self, *, user_id: str, app_metadata: dict[str, Any]
    ) -> Auth0User: ...


class Auth0ManagementClient:
    """Thin, M2M-authenticated Auth0 Management API v2 client.

    Construction requires M2M credentials; absence raises
    ``Auth0ManagementError`` (these are not required merely because
    AUTH_CLIENT_MODE=AUTH0, so the guard lives here, not in Settings).
    Construction opens no network connection (``httpx.AsyncClient`` is lazy);
    the live Auth0 tenant is never contacted until a method is awaited.
    """

    def __init__(
        self, settings: Settings, *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        client_id = settings.auth0_mgmt_client_id
        client_secret = settings.auth0_mgmt_client_secret
        audience = settings.auth0_mgmt_audience
        if not client_id or not client_secret or not audience:
            raise Auth0ManagementError(
                "Auth0ManagementClient requires auth0_mgmt_client_id, "
                "auth0_mgmt_client_secret, and auth0_mgmt_audience",
                has_client_id=bool(client_id),
                has_client_secret=bool(client_secret),
                has_audience=bool(audience),
            )
        self._client_id = client_id
        self._client_secret = client_secret
        # The Management audience is also the API base URL (Auth0 convention:
        # audience == https://<domain>/api/v2/). Ends with '/', so relative
        # paths join under /api/v2/.
        self._audience = audience
        # The M2M token endpoint is the issuer's oauth/token (issuer ends '/').
        self._token_url = f"{settings.jwt_issuer}oauth/token"
        self._client = http_client or httpx.AsyncClient(
            base_url=audience, timeout=_HTTP_TIMEOUT_SECONDS
        )
        self._token: str | None = None
        self._token_expiry_monotonic: float = 0.0
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        """Dispose the underlying HTTP client (call at lifespan shutdown)."""
        await self._client.aclose()

    # -- M2M token ----------------------------------------------------------

    async def _get_token(self) -> str:
        """Return a cached M2M access token, fetching / refreshing on expiry.

        Serialised by a lock so concurrent callers do not each fetch a token
        (the warm path returns the cached token without a network call).
        """
        async with self._token_lock:
            now = time.monotonic()
            if self._token is not None and now < self._token_expiry_monotonic:
                return self._token
            try:
                resp = await self._client.post(
                    self._token_url,
                    json={
                        "client_id": self._client_id,
                        "client_secret": self._client_secret,
                        "audience": self._audience,
                        "grant_type": "client_credentials",
                    },
                )
            except httpx.HTTPError as e:
                raise Auth0ManagementError(
                    f"Auth0 M2M token request failed at transport: {e}",
                    operation="token",
                ) from e
            if resp.status_code != 200:
                raise Auth0ManagementError(
                    f"Auth0 M2M token endpoint returned {resp.status_code}",
                    operation="token",
                    status_code=resp.status_code,
                )
            try:
                data = resp.json()
                access_token: str = data["access_token"]
                expires_in = int(data["expires_in"])
            except (ValueError, KeyError, TypeError) as e:
                raise Auth0ManagementError(
                    "Auth0 M2M token response was malformed", operation="token"
                ) from e
            self._token = access_token
            self._token_expiry_monotonic = now + expires_in - _TOKEN_SKEW_SECONDS
            return access_token

    # -- request helper -----------------------------------------------------

    async def _send(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        json: Any | None = None,
        params: dict[str, Any] | None = None,
    ) -> httpx.Response:
        token = await self._get_token()
        headers = {"Authorization": f"Bearer {token}"}
        try:
            return await self._client.request(
                method, url, json=json, params=params, headers=headers
            )
        except httpx.HTTPError as e:
            raise Auth0ManagementError(
                f"Auth0 Management transport error on {operation}: {e}",
                operation=operation,
            ) from e

    @staticmethod
    def _raise_for_status(
        resp: httpx.Response, operation: str, *, expected: tuple[int, ...]
    ) -> None:
        if resp.status_code not in expected:
            excerpt = _error_body_excerpt(resp)
            raise Auth0ManagementError(
                f"Auth0 Management {operation} returned "
                f"{resp.status_code}: {excerpt}",
                operation=operation,
                status_code=resp.status_code,
                body_excerpt=excerpt,
            )

    # -- Organizations ------------------------------------------------------

    async def create_organization(self, *, name: str, display_name: str) -> Organization:
        resp = await self._send(
            "POST",
            "organizations",
            operation="create_organization",
            json={"name": name, "display_name": display_name},
        )
        self._raise_for_status(resp, "create_organization", expected=(201,))
        return Organization.model_validate(resp.json())

    async def get_organization_by_name(self, name: str) -> Organization | None:
        resp = await self._send(
            "GET", f"organizations/name/{name}", operation="get_organization_by_name"
        )
        if resp.status_code == 404:
            return None
        self._raise_for_status(resp, "get_organization_by_name", expected=(200,))
        return Organization.model_validate(resp.json())

    # -- Users --------------------------------------------------------------

    async def create_user(
        self,
        *,
        email: str,
        connection: str,
        app_metadata: dict[str, Any] | None = None,
        email_verified: bool = False,
    ) -> Auth0User:
        body: dict[str, Any] = {
            "email": email,
            "connection": connection,
            "email_verified": email_verified,
            # Required by Auth0 Database connections on POST /users. A
            # throwaway single-use password (never stored/logged/returned);
            # the user sets their own via the password-change ticket.
            "password": _generate_initial_password(),
        }
        if app_metadata is not None:
            body["app_metadata"] = app_metadata
        resp = await self._send("POST", "users", operation="create_user", json=body)
        self._raise_for_status(resp, "create_user", expected=(201,))
        return Auth0User.model_validate(resp.json())

    async def get_user_by_email(self, email: str) -> Auth0User | None:
        resp = await self._send(
            "GET", "users-by-email", operation="get_user_by_email", params={"email": email}
        )
        self._raise_for_status(resp, "get_user_by_email", expected=(200,))
        data = resp.json()
        if not data:
            return None
        return Auth0User.model_validate(data[0])

    async def add_organization_member(self, *, org_id: str, user_id: str) -> None:
        resp = await self._send(
            "POST",
            f"organizations/{org_id}/members",
            operation="add_organization_member",
            json={"members": [user_id]},
        )
        self._raise_for_status(resp, "add_organization_member", expected=(204,))

    async def update_user_app_metadata(
        self, *, user_id: str, app_metadata: dict[str, Any]
    ) -> Auth0User:
        resp = await self._send(
            "PATCH",
            f"users/{user_id}",
            operation="update_user_app_metadata",
            json={"app_metadata": app_metadata},
        )
        self._raise_for_status(resp, "update_user_app_metadata", expected=(200,))
        return Auth0User.model_validate(resp.json())

    async def create_password_change_ticket(
        self, *, user_id: str, result_url: str
    ) -> str:
        """Generate a password-change ticket for a pre-created user; returns the
        ticket URL. Auth0 does not send an email for
        tickets; CM delivers the URL via SendGrid. Failures map to
        Auth0ManagementError.
        """
        resp = await self._send(
            "POST",
            "tickets/password-change",
            operation="create_password_change_ticket",
            json={"user_id": user_id, "result_url": result_url},
        )
        # Auth0 returns 201 Created for tickets; accept 200 defensively.
        self._raise_for_status(
            resp, "create_password_change_ticket", expected=(200, 201)
        )
        data = resp.json()
        try:
            ticket: str = data["ticket"]
        except (KeyError, TypeError) as e:
            raise Auth0ManagementError(
                "Auth0 password-change ticket response missing 'ticket'",
                operation="create_password_change_ticket",
            ) from e
        return ticket

    async def update_user_email(
        self,
        *,
        user_id: str,
        email: str,
        connection: str,
        email_verified: bool = True,
    ) -> None:
        """Update a user's email in Auth0.

        ``connection`` is REQUIRED: the Management API needs it for email
        updates on database connections. ``email_verified=True`` per D-42
        (staff-driven authority, no re-verification round trip). Failures map
        to Auth0ManagementError. Note: a genuine email change invalidates the
        user's active Auth0 sessions (Auth0's own behavior).
        """
        resp = await self._send(
            "PATCH",
            f"users/{user_id}",
            operation="update_user_email",
            json={
                "email": email,
                "connection": connection,
                "email_verified": email_verified,
            },
        )
        self._raise_for_status(resp, "update_user_email", expected=(200,))
