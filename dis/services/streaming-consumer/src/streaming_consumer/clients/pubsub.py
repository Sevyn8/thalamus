"""The ingress.ready subscriber: pull loop + the audit-and-nack disposition.

Startup REQUIRES the subscription to exist and raises loudly if it does not —
provisioning lives in ``tools/local/create_topics.py`` (``make topics-create``),
NEVER in consumer runtime code. The client is emulator-or-ambient: the emulator
when ``PUBSUB_EMULATOR_HOST`` is set (the ``pubsub_v1`` client honours it
natively), real Pub/Sub via ambient service-account credentials when it is not.

Message routing (audit-and-nack with a quarantine carve-out — see orchestrate.py):

- ``written`` → ack.
- ``quarantined`` → **ack**. The chunk is HELD in the quarantine store (the
  fail-loud write already succeeded) and the QUARANTINED audit emitted; the ack
  breaks the deterministic-failure redeliver loop at its source.
- any failed disposition or any raised pipeline error → **nack** (the pipeline
  already emitted the FAILURE audit; bronze remains the recoverable source).
  This includes a FAILED QUARANTINE WRITE (the pipeline falls back to raise /
  ``failed_*`` so the held data is never acked-and-lost) and the self-heal
  exclusions (``HOT_POSITION_MISSING``, the store-miss contract violation) —
  redelivery is their designed recovery; the Pub/Sub dead-letter policy
  backstops.
- the ONE pre-pipeline ack-on-failure: an unparseable envelope
  (``EventContractError`` at parse). Identity may be unknowable there, so a
  tenant-stamped audit row may be impossible, and a redelivery fails
  identically. No quarantine either — the quarantine tables' ``tenant_id`` is
  NOT NULL.

No ordering key is consumed: canonical correctness is event-time-based
(read-time dedup + the conditional upsert), so an ordering key would defend
nothing the consumer needs.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from google.api_core.exceptions import (
    DeadlineExceeded,
    RetryError,
    ServerError,
    TooManyRequests,
)
from sqlalchemy.exc import (
    DisconnectionError,
    InterfaceError,
    InternalError,
    OperationalError,
)
from sqlalchemy.exc import TimeoutError as SATimeoutError

from dis_core.errors import DisError, EventContractError
from dis_core.logging import get_logger
from streaming_consumer.config import INGRESS_READY_SUBSCRIPTION, SERVICE_NAME
from streaming_consumer.envelope import parse_ingress_ready
from streaming_consumer.health import Heartbeat
from streaming_consumer.orchestrate import ConsumerPipeline

if TYPE_CHECKING:
    from google.cloud import pubsub_v1

_log = get_logger(SERVICE_NAME)

Decision = Literal["ack", "nack"]

# Tier 2 of run_forever's swallow: errors that are genuinely TRANSIENT, warned and
# retried. Deliberately NARROW - anything not listed falls through to the tier-3
# catch, which logs at ERROR under a BUG marker. Nothing propagates from any tier,
# so a class missed here is loud, not fatal.
#
# api_core.ServerError is the 5xx-class transport parent (ServiceUnavailable,
# InternalServerError, GatewayTimeout).
#
# IT DELIBERATELY EXCLUDES THE 4xx-CLASS ClientError BRANCH. PermissionDenied,
# NotFound and InvalidArgument are CONFIG errors: no amount of retrying fixes a
# missing IAM binding or a wrong subscription name. Retried in silence forever is
# the exact shape of the prune bug — a permission failure that looks like a
# transient blip, retries indefinitely, and never surfaces because nothing ever
# logs it at a level anyone queries. They belong in the tier-3 BUG catch, and a
# 403 on the subscription is covered by a test there.
#
# DeadlineExceeded is a ServerError subclass, so its own clause must come FIRST.
#
# The SQLAlchemy set is here because poll_once runs the whole consumer pipeline,
# including the Cloud SQL dual-write - a DB blip mid-pass is a transport blip.
_TRANSIENT_POLL_ERRORS = (
    ServerError,  # Pub/Sub 5xx: ServiceUnavailable, InternalServerError, GatewayTimeout
    TooManyRequests,  # 429 quota pushback
    RetryError,  # api_core retry budget exhausted on a retryable class
    OperationalError,  # connection lost, server restart, too many connections, deadlock
    InterfaceError,  # connection broken out from under the driver
    InternalError,  # server-side internal / aborted transaction
    DisconnectionError,  # pool-level disconnect (not a DBAPIError)
    SATimeoutError,  # pool checkout timeout (not a DBAPIError)
    OSError,  # raw socket failure, e.g. ConnectionRefusedError
)


async def process_message(pipeline: ConsumerPipeline, data: bytes) -> Decision:
    """Route one raw message body: parse, process, decide ack/nack."""
    try:
        event = parse_ingress_ready(data)
    except EventContractError as exc:
        _log.bind(stage="intake", tenant_id=exc.tenant_id, trace_id=exc.trace_id).error(
            "ingress.ready envelope rejected (terminal): %s", exc
        )
        return "ack"

    log = _log.bind(stage="intake", tenant_id=str(event.tenant_id), trace_id=str(event.trace_id))
    try:
        outcome = await pipeline.process(event)
    except Exception as exc:
        log.error("chunk failed (nacked; FAILURE audit emitted — audit-and-nack): %s", exc)
        return "nack"
    if outcome.disposition == "quarantined":
        # The chunk is held (fail-loud write succeeded), so the ack breaks the
        # deterministic-failure redeliver loop at its source.
        log.info("chunk quarantined (acked; held in quarantine.* with QUARANTINED audit)")
        return "ack"
    if outcome.disposition != "written":
        log.error("chunk failed validation: %s (nacked — audit-and-nack)", outcome.disposition)
        return "nack"
    log.info("processed: %s", outcome.disposition)
    return "ack"


@dataclass
class Subscriber:
    """The long-running pull loop over the consumer's ingress.ready subscription."""

    project_id: str
    pipeline: ConsumerPipeline
    max_messages: int = 10
    # Beaten once per loop cycle UNCONDITIONALLY (all modes — the loop never
    # branches on environment; only the healthz SERVER is toggled, main.py).
    heartbeat: Heartbeat = field(default_factory=Heartbeat)

    def __post_init__(self) -> None:
        import os

        mode = "emulator" if os.environ.get("PUBSUB_EMULATOR_HOST") else "ambient"
        _log.bind(stage="startup").info("pubsub subscriber constructed", extra={"pubsub_mode": mode})
        from google.cloud import pubsub_v1

        self._client = pubsub_v1.SubscriberClient()
        self._sub_path = self._client.subscription_path(self.project_id, INGRESS_READY_SUBSCRIPTION)
        self._require_subscription()

    def _require_subscription(self) -> None:
        """Fail loud at startup when the subscription is absent (errors, never skips)."""
        from google.api_core.exceptions import NotFound

        try:
            self._client.get_subscription(request={"subscription": self._sub_path})
        except NotFound as exc:
            raise DisError(
                f"subscription {INGRESS_READY_SUBSCRIPTION!r} does not exist on project "
                f"{self.project_id!r}; run `make topics-create` to provision it"
            ) from exc

    def _pull(self) -> Any:
        return self._client.pull(
            request={"subscription": self._sub_path, "max_messages": self.max_messages},
            timeout=10,
        )

    async def poll_once(self) -> int:
        """One pull + process + ack/nack pass. Returns the number of messages handled."""
        response = await asyncio.to_thread(self._pull)
        ack_ids: list[str] = []
        nack_ids: list[str] = []
        received: list[pubsub_v1.types.ReceivedMessage] = list(response.received_messages)
        for message in received:
            decision = await process_message(self.pipeline, message.message.data)
            (ack_ids if decision == "ack" else nack_ids).append(message.ack_id)
        if ack_ids:
            await asyncio.to_thread(
                self._client.acknowledge,
                request={"subscription": self._sub_path, "ack_ids": ack_ids},
            )
        if nack_ids:
            # Deadline 0 = immediate redelivery (the emulator honours it);
            # read-time dedup + the conditional upsert absorb the replay.
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
        log = _log.bind(stage="subscriber")
        log.info("subscribed; pulling from %s", self._sub_path)
        while True:
            # The readiness heartbeat, written unconditionally in every
            # mode (local / Cloud Run Service / Worker Pools) — only the healthz
            # server that READS it is toggled. A dead/hung loop stops beating and
            # /healthz goes stale.
            self.heartbeat.beat()
            try:
                await self.poll_once()
            except DeadlineExceeded:
                # An EMPTY subscription is the normal steady state. The synchronous
                # pull holds the connection open until the 10s client deadline and
                # then raises DeadlineExceeded, unwrapped (it is NOT in pull's
                # api_core retry predicate, unlike streaming_pull's). Logging that at
                # ERROR with a traceback produced ~7,800 entries per instance per day
                # and buried real output. It is a non-event: debug, then loop.
                log.debug("empty pull; no messages this pass")
                await asyncio.sleep(1)
            except _TRANSIENT_POLL_ERRORS:
                # The loop must survive transient pull/transport errors; each
                # message's own routing already decided ack/nack.
                log.warning("poll pass failed; retrying")
                await asyncio.sleep(1)
            except Exception:  # noqa: BLE001 - the loop must never die (see tier comment)
                # Anything else is a PROGRAMMING or CONFIG error: a TypeError in the
                # pipeline, a 403 on the subscription, a malformed request. Still
                # swallowed, because a dead loop is worse than a noisy one, but at
                # ERROR with a traceback under a `bug` marker so it is findable.
                log.bind(bug=True).exception("BUG: poll pass raised a non-transient error; retrying")
                await asyncio.sleep(1)
