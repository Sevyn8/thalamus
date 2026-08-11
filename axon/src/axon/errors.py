"""Axon's typed errors. Two, and the split is what the caller does about them.

``ChannelSendError`` means the provider refused or the transport failed. It is recorded on the
ledger as ``state='failed'`` with the detail, and it never reaches the caller of a fire-and-record
send: an enable must not fail because an email did not go out.

``LedgerWriteError`` means the row could not be written. It is the deeper failure, and it is the
one nothing in this slice can mitigate. See ``send.py`` for why the queue exists.

MODELLED ON CM'S ``EmailSendError``, which carries ``provider`` and ``status_code`` as structured
context rather than formatting them into the message. Same discipline here: the credential is
NEVER in the message, in the context, or in a log line.
"""

from __future__ import annotations


class AxonError(Exception):
    """Base for everything this module raises."""


class ChannelSendError(AxonError):
    """A provider refused the message, or the transport to it failed.

    ``detail`` is what gets written to ``failure_detail`` on the ledger row. It carries the
    provider's status and its own words where it gave any, because a person diagnosing this
    without the provider console has nothing else. It NEVER carries the credential.
    """

    def __init__(self, detail: str, *, provider: str, status_code: int | None = None) -> None:
        super().__init__(detail)
        self.detail = detail
        self.provider = provider
        self.status_code = status_code


class LedgerWriteError(AxonError):
    """The delivery row could not be written.

    Distinct from a send failure ON PURPOSE. A failed send leaves a row saying so; this leaves
    NOTHING, which is the one outcome that is invisible from the database afterwards.
    """
