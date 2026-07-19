"""Slice 2d-send offline unit tests for SendGridEmailSender.

No network: an httpx.MockTransport backs the injected AsyncClient, so the real
request-building runs while SendGrid is never contacted. Covers the request
shape (endpoint, Bearer auth, body), 202 success, and failure mapping to
EmailSendError.
"""
import json
from typing import Any

import httpx
import pytest

from admin_backend.config import Settings
from admin_backend.email_sender import EmailSender, SendGridEmailSender
from admin_backend.errors import EmailSendError


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(  # type: ignore[call-arg]
        sendgrid_api_key="SG.test-key",
        sendgrid_from_email="noreply@sevyn8.com",
    )


def _sender(settings: Settings, handler: Any) -> SendGridEmailSender:
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return SendGridEmailSender(settings, http_client=http)


def test_construction_requires_api_key() -> None:
    no_key = Settings()  # type: ignore[call-arg]  # sendgrid_api_key defaults None
    with pytest.raises(EmailSendError):
        SendGridEmailSender(no_key)


def test_satisfies_protocol(settings: Settings) -> None:
    sender = _sender(settings, lambda r: httpx.Response(202))
    assert isinstance(sender, EmailSender)


async def test_send_email_request_shape(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert str(request.url) == "https://api.sendgrid.com/v3/mail/send"
        assert request.headers.get("authorization") == "Bearer SG.test-key"
        body = json.loads(request.content)
        assert body == {
            "personalizations": [{"to": [{"email": "invitee@tenant.test"}]}],
            "from": {"email": "noreply@sevyn8.com"},
            "subject": "Your Ithina invitation",
            "content": [{"type": "text/plain", "value": "set your password: https://x/t"}],
        }
        return httpx.Response(202)

    await _sender(settings, handler).send_email(
        to="invitee@tenant.test",
        subject="Your Ithina invitation",
        body="set your password: https://x/t",
    )


async def test_send_email_non_202_maps_to_typed_error(settings: Settings) -> None:
    sender = _sender(settings, lambda r: httpx.Response(400, json={"errors": []}))
    with pytest.raises(EmailSendError):
        await sender.send_email(to="x@y.test", subject="s", body="b")


async def test_send_email_transport_error_maps_to_typed_error(settings: Settings) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    sender = _sender(settings, handler)
    with pytest.raises(EmailSendError):
        await sender.send_email(to="x@y.test", subject="s", body="b")
