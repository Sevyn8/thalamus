"""The SendGrid v3 email adapter.

PORTED FROM ``cm-backend/src/admin_backend/email_sender.py``, NOT WRITTEN FRESH. That file is a
working client against the same provider on the same account, and four of its decisions are
carried over here verbatim because each was paid for once already:

  1. THE ENDPOINT IS ABSOLUTE and the client sets no base_url.
  2. CONSTRUCTION IS GUARDED ON THE CREDENTIAL. No key, no adapter. A client that constructs
     without a credential is one that fails at the first send instead of at boot.
  3. A NON-202 RESPONSE OR A TRANSPORT ERROR IS A TYPED ERROR, never a raw exception escaping
     into a caller that cannot classify it.
  4. TRACKING IS DISABLED IN CODE, and the reason is recorded at the setting itself.

WHAT IS DELIBERATELY NOT CARRIED OVER. CM's sender is constructed once in a FastAPI lifespan and
its ``send_email`` takes ``(to, subject, body)``. This one takes a ``Message`` carrying its
channel, because Axon's port is multi-channel. The recipe inside is the same JSON body.

202 IS ACCEPTANCE, NOT DELIVERY, and this adapter cannot tell the difference. It returns on 202
and the ledger records ``accepted``. Whether the mail arrived is knowable only from an inbound
delivery receipt, and that plane does not exist. An adapter that returned something called
"delivered" would be asserting what it cannot observe.

WHAT CORRELATING A FUTURE RECEIPT WILL NEED, stated as unknown rather than guessed: a receipt
webhook has to be matched back to a ledger row, which needs an identifier both sides share.
SendGrid returns one on the response, and CM's client does not read it. This adapter does not
either, because inventing a column for a value whose name and shape has not been verified against
the provider would be exactly the kind of guess this repository does not make. Whatever builds
receipt webhooks establishes it and adds the column then.
"""

from __future__ import annotations

import httpx

from axon.channel import Channel, Message
from axon.errors import ChannelSendError

# SendGrid v3 Mail Send. Absolute, as in CM's client.
_SENDGRID_URL = "https://api.sendgrid.com/v3/mail/send"
_HTTP_TIMEOUT_SECONDS = 10.0

_PROVIDER = "sendgrid"

# The only response SendGrid gives for an accepted message.
_ACCEPTED = 202


class SendGridEmailAdapter:
    """Thin SendGrid v3 Mail Send client (plain text), behind the Channel port."""

    def __init__(
        self,
        *,
        api_key: str,
        from_email: str,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        # GUARDED, like CM's. An adapter without a credential can only fail later, at a moment
        # when a message is already in flight and an operator is waiting.
        if not api_key:
            raise ChannelSendError("SendGridEmailAdapter requires an API key", provider=_PROVIDER)
        # AND ON THE SENDER. SendGrid refuses a from-address that is not a verified sender on
        # the account, per message, at runtime. An empty one fails every send with something
        # that reads like a provider outage, so it is refused at construction where the message
        # can name the actual problem.
        if not from_email:
            raise ChannelSendError(
                "SendGridEmailAdapter requires a from-address, and it must be a "
                "SendGrid-VERIFIED sender on the account or every send is refused",
                provider=_PROVIDER,
            )
        self._api_key = api_key
        self._from_email = from_email
        self._client = http_client or httpx.AsyncClient(timeout=_HTTP_TIMEOUT_SECONDS)

    @property
    def channel(self) -> Channel:
        return Channel.EMAIL

    @property
    def provider(self) -> str:
        return _PROVIDER

    async def aclose(self) -> None:
        """Dispose the underlying HTTP client (call at lifespan shutdown)."""
        await self._client.aclose()

    async def send(self, message: Message) -> None:
        if message.channel is not Channel.EMAIL:
            raise ChannelSendError(
                f"SendGridEmailAdapter received a {message.channel} message; it serves email only",
                provider=_PROVIDER,
            )
        if not message.subject:
            raise ChannelSendError("an email message needs a subject", provider=_PROVIDER)

        payload = {
            "personalizations": [{"to": [{"email": message.recipient}]}],
            "from": {"email": self._from_email},
            "subject": message.subject,
            "content": [{"type": "text/plain", "value": message.body}],
            # DISABLED IN CODE, NOT BY A DASHBOARD TOGGLE, and the reason is CM's and is worth
            # repeating where the setting is: SendGrid click tracking rewrites every link
            # through url####.sevyn8.com, which serves an invalid certificate
            # (ERR_CERT_COMMON_NAME_INVALID). A dashboard setting is account-wide, invisible
            # from this repository, and would silently apply to every message Axon ever sends.
            # Setting it here means the guarantee travels with the send path.
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
            response = await self._client.post(_SENDGRID_URL, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            # The exception text, not the credential. httpx puts the URL in its message and the
            # key is a header, so this is safe; it is called out because the next person adding
            # context here has to keep it true.
            raise ChannelSendError(f"SendGrid transport error: {exc}", provider=_PROVIDER) from exc
        if response.status_code != _ACCEPTED:
            raise ChannelSendError(
                f"SendGrid returned {response.status_code}",
                provider=_PROVIDER,
                status_code=response.status_code,
            )
