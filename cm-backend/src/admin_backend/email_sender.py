"""Outbound email (SendGrid) — CM's first email integration (Slice 2d-send, D-41).

Raw httpx behind a thin sender + a runtime_checkable ``EmailSender`` Protocol, so
the send-invitation action and its tests inject a fake, mirroring the
``Auth0ManagementClient`` seam (2b). Constructed once in the lifespan, guarded on
``sendgrid_api_key`` (STUB / unconfigured leaves it None). A non-202 response or
transport error maps to ``EmailSendError`` (a ServerError), never a raw 500. The
test suite never hits real SendGrid.

Not on the ``Auth0ManagementClient``: email is a separate service (different host,
auth, and lifecycle) with its own seam.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from admin_backend.config import Settings
from admin_backend.errors import EmailSendError

# SendGrid v3 Mail Send endpoint (absolute; the client sets no base_url).
_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_HTTP_TIMEOUT_SECONDS = 10.0


@runtime_checkable
class EmailSender(Protocol):
    """The email operation the send-invitation action depends on. The action and
    its tests inject a fake satisfying this Protocol."""

    async def send_email(self, *, to: str, subject: str, body: str) -> None: ...


class SendGridEmailSender:
    """Thin SendGrid v3 Mail Send client (plain-text). Construction requires an
    API key (guarded); it opens no connection until a send is awaited."""

    def __init__(
        self, settings: Settings, *, http_client: httpx.AsyncClient | None = None
    ) -> None:
        api_key = settings.sendgrid_api_key
        if not api_key:
            raise EmailSendError(
                "SendGridEmailSender requires sendgrid_api_key",
                has_api_key=False,
            )
        self._api_key = api_key
        self._from_email = settings.sendgrid_from_email
        self._client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)

    async def aclose(self) -> None:
        """Dispose the underlying HTTP client (call at lifespan shutdown)."""
        await self._client.aclose()

    async def send_email(self, *, to: str, subject: str, body: str) -> None:
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self._from_email},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body}],
            # Per-message tracking is disabled on every transactional send.
            # The invitation body carries a one-time Auth0 password-change
            # ticket URL; SendGrid click tracking rewrites links through
            # url####.sevyn8.com, which serves an invalid certificate
            # (ERR_CERT_COMMON_NAME_INVALID) and must never sit between the
            # user and a single-use credential URL. Set in code, not by a
            # dashboard toggle, so the guarantee travels with the send path.
            "tracking_settings": {
                "click_tracking": {"enable": False, "enable_text": False},
                "open_tracking": {"enable": False},
            },
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = await self._client.post(_SENDGRID_URL, json=payload, headers=headers)
        except httpx.HTTPError as e:
            raise EmailSendError(
                f"SendGrid transport error: {e}", provider="sendgrid"
            ) from e
        if resp.status_code != 202:
            raise EmailSendError(
                f"SendGrid returned {resp.status_code}",
                provider="sendgrid",
                status_code=resp.status_code,
            )
