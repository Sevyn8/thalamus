"""The pull loop over ``axon-send-requested-sub``: pull, send, record, ack.

=================================================================================================
ACK AND NACK, AND WHAT EACH ONE MEANS HERE
=================================================================================================
  ACK   the ledger holds a row for this delivery_id. That is true whether this pass wrote it
        (the normal path) or a previous pass already had (a redelivery). It is ALSO true when the
        provider REFUSED the send: a refusal is recorded as state='failed' with the detail, which
        is evidence, and retrying a 403 produces another 403. Acking a recorded failure is the
        loop working, not the loop giving up.
  NACK  the ledger holds nothing. The send may or may not have happened; the write did not. The
        message is redelivered, and the redelivery is the only thing that can still produce a row.

A PLAIN NACK, NOT ``ack_deadline_seconds = 0``. streaming-consumer nacks with an immediate
deadline and its own comment explains the cost: attempts then accumulate at LOOP SPEED rather
than wall-clock speed. There it is absorbed by a 100-attempt budget. Here the budget is 5 and
every attempt is a possible duplicate email, so the subscription's retry_policy backoff is what
should govern the pace, and a plain nack is what lets it.

=================================================================================================
AT-LEAST-ONCE. THE LEDGER WRITE IS IDEMPOTENT, THE SEND IS NOT.
=================================================================================================
``delivery_id`` is minted by the producer and travels in the envelope, so a redelivered message
reaches the same ``pk_platform_deliveries`` and the second INSERT is refused. See ledger.py.

THE WINDOW THAT REMAINS IS A CRASH BETWEEN THE PROVIDER'S 202 AND THE LEDGER COMMIT. On
redelivery there is no row to find, this loop cannot know the message already went, and it sends
again. The result is a duplicate internal email, bounded by max_delivery_attempts = 5. Reading
the ledger first would not help, because after a failed write there is nothing to read. Writing a
`queued` row first and updating it would not help either and costs the append-only property; see
send.py, which argues both.

The construct that WOULD close it is a provider-side idempotency key, and whether SendGrid v3
accepts one is UNVERIFIED. It is a thing to check, not a design assumption.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any, Literal

from axon import Channel, ChannelAdapter, Message, SendRequested, send_platform
from google.api_core.exceptions import (
    DeadlineExceeded,
    RetryError,
    ServerError,
    TooManyRequests,
)
from sqlalchemy.ext.asyncio import AsyncEngine

from axon_sender.config import SUBSCRIPTION
from axon_sender.health import Heartbeat
from dis_core.logging import get_logger

__all__ = ["Decision", "Subscriber", "process_message"]

_log = get_logger("axon-sender")

# The middle tier of run_forever's three: errors that a retry can plausibly clear.
# DELIBERATELY NARROW. Anything not listed falls through to the BUG tier, which logs at
# ERROR with a traceback, so a class missed here is loud rather than silently retried.
#
# DeadlineExceeded IS A ServerError SUBCLASS and is therefore NOT in this tuple: it gets
# its own clause ABOVE this one in run_forever. If that ordering is ever reversed, the
# empty pull becomes a warning again and this whole change is undone silently. The test
# suite asserts the two together for that reason.
#
# IT EXCLUDES THE 4xx CLASS, and that exclusion is the point rather than an oversight.
# PermissionDenied, NotFound and InvalidArgument are configuration errors; no amount of
# retrying fixes a missing IAM binding or a wrong subscription name. None of them is a
# ServerError subclass, so they fall to the BUG tier by construction.
#
# NO SQLAlchemy CLASSES, WHICH IS WHERE THIS DIVERGES FROM streaming-consumer. That
# service lists them because its poll_once runs a Cloud SQL dual-write inline. Axon's
# database work goes through send_platform, which catches ChannelSendError and
# LedgerWriteError and RETURNS an outcome rather than raising (axon/src/axon/send.py,
# and its docstring says it raises nothing). So the database is not expected to surface
# here. If one ever escapes anyway it lands in the BUG tier at ERROR with a traceback,
# which is the safe direction to be wrong in.
_TRANSIENT_POLL_ERRORS = (
    ServerError,  # Pub/Sub 5xx: ServiceUnavailable, InternalServerError, GatewayTimeout
    TooManyRequests,  # 429 quota pushback; not a ServerError subclass, so listed
    RetryError,  # api_core retry budget exhausted on a retryable class
    OSError,  # raw socket failure, e.g. ConnectionRefusedError
)

Decision = Literal["ack", "nack"]


async def process_message(
    *,
    engine: AsyncEngine,
    adapter: ChannelAdapter,
    raw: bytes,
) -> Decision:
    """Route one raw message body: parse, send, record, decide.

    A MALFORMED ENVELOPE IS A NACK, NOT AN ACK. It is either a producer bug or a version skew,
    and both deserve the dead-letter lane after the attempts run out rather than being discarded
    silently on the first pass. The alternative, acking what cannot be parsed, makes a producer
    bug invisible: the messages leave the queue and nothing anywhere records that they existed.
    """
    try:
        envelope = SendRequested.from_json(raw)
    except Exception as exc:  # noqa: BLE001 - any parse failure is the same decision
        _log.bind(stage="parse").error(
            "envelope could not be read; nacked",
            extra={"event": "axon.envelope.unreadable", "detail": str(exc)},
        )
        return "nack"

    log = _log.bind(stage="send", delivery_id=str(envelope.delivery_id))

    # THE ADAPTER IS CHOSEN BY THE ENVELOPE'S CHANNEL, and there is exactly one. A non-email
    # channel cannot be produced today (the platform ledger CHECK-forces email), so this is a
    # guard against a future producer rather than a live branch, and it nacks rather than
    # pretending: a WhatsApp message handed to the email adapter would be refused by the adapter
    # anyway, and this says why one layer earlier.
    if envelope.channel is not Channel.EMAIL:
        log.error(
            "no adapter for this channel; nacked",
            extra={"event": "axon.channel.unsupported", "channel": str(envelope.channel)},
        )
        return "nack"

    outcome = await send_platform(
        engine=engine,
        adapter=adapter,
        message=Message(
            channel=envelope.channel,
            recipient=envelope.recipient,
            subject=envelope.subject,
            body=envelope.body,
        ),
        delivery_id=envelope.delivery_id,
        notification_class=envelope.notification_class,
        subject_kind=envelope.subject_kind,
        subject_id=envelope.subject_id,
        actor_subject=envelope.actor_subject,
    )

    if not outcome.recorded:
        # The one nack that is not about the message: the ledger is unreachable. The send may
        # already have happened, which is exactly the duplicate window the module docstring names.
        log.error(
            "ledger write failed; nacked for redelivery",
            extra={"event": "axon.ledger.write_failed", "detail": outcome.detail},
        )
        return "nack"

    if outcome.duplicate:
        # NOT AN ERROR AND WORTH A LINE ANYWAY. A duplicate proves a redelivery happened, which is
        # the only in-band evidence that a previous attempt got as far as the ledger and then
        # failed to ack. A run with many of these is a run where something is nacking after the
        # write, and nothing else would say so.
        log.info(
            "already recorded; redelivery acked without a second row",
            extra={"event": "axon.delivery.duplicate", "state": str(outcome.state)},
        )
        return "ack"

    log.info(
        "delivery recorded",
        extra={
            "event": "axon.delivery.recorded",
            "state": str(outcome.state),
            "detail": outcome.detail,
        },
    )
    return "ack"


@dataclass
class Subscriber:
    """The long-running pull loop over the sender's subscription."""

    project_id: str
    engine: AsyncEngine
    adapter: ChannelAdapter
    max_messages: int = 10
    heartbeat: Heartbeat = field(default_factory=Heartbeat)

    def __post_init__(self) -> None:
        import os

        mode = "emulator" if os.environ.get("PUBSUB_EMULATOR_HOST") else "ambient"
        _log.bind(stage="startup").info("pubsub subscriber constructed", extra={"pubsub_mode": mode})
        from google.cloud import pubsub_v1

        self._client = pubsub_v1.SubscriberClient()
        self._sub_path = self._client.subscription_path(self.project_id, SUBSCRIPTION)
        self._require_subscription()

    def _require_subscription(self) -> None:
        """Fail loud at startup when the subscription is absent.

        WITHOUT THIS THE FAILURE IS SILENT. A pull against a subscription that does not exist
        raises per pass, the loop swallows it to stay alive, and the service reports healthy
        while draining nothing. Checked once at construction so the revision refuses to start.
        """
        from google.api_core.exceptions import NotFound

        try:
            self._client.get_subscription(request={"subscription": self._sub_path})
        except NotFound as exc:
            raise RuntimeError(
                f"subscription {SUBSCRIPTION!r} does not exist on project {self.project_id!r}. "
                "It is created by terraform alongside the topic and the dead-letter lane; a "
                "revision deployed before that apply cannot drain anything"
            ) from exc

    def _pull(self) -> Any:
        return self._client.pull(
            request={"subscription": self._sub_path, "max_messages": self.max_messages},
            timeout=10,
        )

    async def poll_once(self) -> int:
        """One pull, process, ack/nack pass. Returns the number of messages handled."""
        response = await asyncio.to_thread(self._pull)
        ack_ids: list[str] = []
        nack_ids: list[str] = []
        received = list(response.received_messages)
        for message in received:
            decision = await process_message(
                engine=self.engine, adapter=self.adapter, raw=message.message.data
            )
            (ack_ids if decision == "ack" else nack_ids).append(message.ack_id)
        if ack_ids:
            await asyncio.to_thread(
                self._client.acknowledge,
                request={"subscription": self._sub_path, "ack_ids": ack_ids},
            )
        if nack_ids:
            # A PLAIN NACK: deadline 0 would redeliver immediately and burn the 5-attempt budget
            # at loop speed. See the module docstring; the subscription's retry_policy governs.
            await asyncio.to_thread(
                self._client.modify_ack_deadline,
                request={
                    "subscription": self._sub_path,
                    "ack_ids": nack_ids,
                    "ack_deadline_seconds": 0,
                },
            )
        return len(received)

    async def run_forever(self) -> None:
        """Pull until the process ends. The loop must never die.

        THE HEARTBEAT IS BEATEN UNCONDITIONALLY at the top of every pass, before the work, so it
        measures the LOOP rather than the success of any one message. A pass that nacks
        everything is still a live loop; a pass that never returns is not, and only the beat can
        tell those apart from outside.
        """
        log = _log.bind(stage="subscriber")
        log.info("subscribed; pulling from %s", self._sub_path)
        while True:
            self.heartbeat.beat()
            try:
                await self.poll_once()
            except DeadlineExceeded:
                # AN EMPTY QUEUE IS THE NORMAL STEADY STATE, NOT A FAILURE. The synchronous pull
                # holds the connection open until the client deadline and then raises
                # DeadlineExceeded, so every pass over an idle subscription arrives here.
                #
                # THIS BRANCH REPLACES A SINGLE HANDLER THAT LOGGED IT AT WARNING AS
                # `axon.poll.failed`, and the comment that defended doing so was built on a
                # misread number. It said streaming-consumer's ~7,800 entries per instance per
                # day came from that queue being busy, and concluded "this queue is far quieter,
                # so the split is not yet earned". The arithmetic says otherwise. Both services
                # pull with timeout=10 and then sleep(1), so a pass takes about eleven seconds
                # and 86400 / 11 is about 7,854. THAT NUMBER IS THE CADENCE, NOT THE TRAFFIC. It
                # is what an idle loop produces no matter how quiet the queue is, and a quieter
                # queue produces MORE of them, because more passes return empty. The condition
                # the old comment set for revisiting was already met the day it was written.
                #
                # DEBUG RATHER THAN SILENCE. A logged non-event at a level nobody queries is what
                # separates "the loop is alive and idle" from "the loop stopped" for whoever
                # raises the level to find out.
                log.debug("empty pull; no messages this pass")
                await asyncio.sleep(1)
            except _TRANSIENT_POLL_ERRORS as exc:
                # A REAL PULL FAILURE, AND IT STAYS LOUD. This is what the WARNING level was
                # always for; it was just being drowned by the branch above. The event name keeps
                # `failed` because this one actually is one. Nothing watches the name: no alert
                # policy, no log-based metric and no dashboard matches on it, which is why this
                # commit needs no Terraform.
                log.warning(
                    "poll pass failed; retrying",
                    extra={"event": "axon.poll.failed", "error_type": type(exc).__name__},
                )
                await asyncio.sleep(1)
            except Exception:  # noqa: BLE001 - a dead loop is worse than a noisy one
                # A PROGRAMMING OR CONFIGURATION ERROR. Still swallowed, because a loop that dies
                # drains nothing, but at ERROR with a traceback under a `bug` marker so it can be
                # found.
                #
                # THE CONCRETE CASE THIS TIER EXISTS FOR IS A 4xx, AND IT MATTERS MORE THAN THE
                # NOISE REDUCTION. PermissionDenied on the subscription is NOT a ServerError
                # subclass, so it does not match the transient tuple and lands here. Under the
                # single handler this replaced, a revision that had lost its IAM binding logged
                # one WARNING line every eleven seconds, indistinguishable from an idle queue,
                # and retried forever while draining nothing. That is a permanent failure wearing
                # a transient's clothes, and it is now an ERROR with a stack trace on the first
                # pass.
                log.bind(bug=True).exception("BUG: poll pass raised a non-transient error; retrying")
                await asyncio.sleep(1)
