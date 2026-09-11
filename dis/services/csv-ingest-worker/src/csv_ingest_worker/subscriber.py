"""The csv.received subscriber: pull loop, terminal-vs-transient routing, ack/nack.

Startup REQUIRES the subscription to exist and raises loudly if it does not —
provisioning lives in ``tools/local/create_topics.py`` (``make topics-create``),
NEVER in worker runtime code, so an absent subscription is a configuration error,
not a silent auto-repair. The client is emulator-or-ambient: the
emulator when ``PUBSUB_EMULATOR_HOST`` is set (the ``pubsub_v1`` client honours it
natively), real Pub/Sub via ambient service-account credentials when it is not.

Message routing:

- terminal (contract/content) failures — a malformed envelope, a path/identity
  mismatch, a detected PII column with no backend — are ACKed after the loud error:
  a redelivery would fail identically (the pipeline already emitted the FAILURE
  audit). Preflight failure is handled INSIDE the pipeline (FAILED bronze row) and
  acks via the normal outcome path.
- everything else (DB/GCS/publish unreachable) is transient: logged and NACKed for
  redelivery, which converges via the idempotency path. The error is handled
  by the messaging layer, not swallowed.
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

from csv_ingest_worker.config import (
    CSV_RECEIVED_SUBSCRIPTION,
    SERVICE_NAME,
)
from csv_ingest_worker.envelope import parse_csv_received
from csv_ingest_worker.health import Heartbeat
from csv_ingest_worker.pipeline import IngestPipeline
from dis_core.errors import (
    CsvIngestError,
    EventContractError,
    EventPathMismatchError,
    PiiBackendNotConfiguredError,
)
from dis_core.logging import get_logger

if TYPE_CHECKING:
    from google.cloud import pubsub_v1

_log = get_logger(SERVICE_NAME)

Decision = Literal["ack", "nack"]

# Contract/content failures: redelivery fails identically, so ack (terminal).
_TERMINAL = (EventContractError, EventPathMismatchError, PiiBackendNotConfiguredError)

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
# The SQLAlchemy set is here because poll_once runs the whole ingest pipeline,
# including the bronze write - a DB blip mid-pass is a transport blip. READ THE
# REACHABILITY NARROWLY: process_message already catches every exception out of
# pipeline.process and turns it into a nack, so these five classes are reachable
# HERE only for a DB error raised OUTSIDE pipeline.process. This tuple is not the
# protection for the pipeline's own DB failures - that decision lives one layer
# down, in process_message.
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


async def process_message(pipeline: IngestPipeline, data: bytes) -> Decision:
    """Route one raw message body: parse, process, decide ack/nack."""
    try:
        event = parse_csv_received(data)
    except EventContractError as exc:
        _log.bind(stage="intake", tenant_id=exc.tenant_id, trace_id=exc.trace_id).error(
            "csv.received envelope rejected (terminal): %s", exc
        )
        return "ack"

    log = _log.bind(stage="intake", tenant_id=str(event.tenant_id), trace_id=str(event.trace_id))
    try:
        outcome = await pipeline.process(event)
    except _TERMINAL as exc:
        log.error("terminal ingest failure (acked; FAILURE audit emitted): %s", exc)
        return "ack"
    except Exception as exc:
        # NOT necessarily transient, and deliberately no longer claiming to be. This
        # catch is blind: a DB blip and a TypeError land here identically. For the
        # blip, redelivery plus the idempotency path does converge; for a
        # programming error nothing is transient and idempotency never converges.
        # The nack is now BOUNDED rather than infinite - dis-csv-received-sub carries
        # a dead_letter_policy (max_delivery_attempts 20) plus a 10s-600s retry
        # backoff, so a message that cannot succeed lands in dis-csv-received-dlq
        # instead of looping forever. Deciding ack-and-audit vs nack per failure
        # class is still open (ledger: the poison-message decision).
        log.error("ingest failure (nacked; bounded by the dead-letter policy): %s", exc)
        return "nack"
    log.info("processed: %s", outcome.disposition)
    return "ack"


@dataclass
class Subscriber:
    """The long-running pull loop over the worker's csv.received subscription."""

    project_id: str
    pipeline: IngestPipeline
    max_messages: int = 10
    # Beaten once per loop cycle UNCONDITIONALLY (all modes — the loop
    # never branches on environment; only the healthz SERVER is toggled, main.py).
    heartbeat: Heartbeat = field(default_factory=Heartbeat)

    def __post_init__(self) -> None:
        import os

        mode = "emulator" if os.environ.get("PUBSUB_EMULATOR_HOST") else "ambient"
        _log.bind(stage="startup").info("pubsub subscriber constructed", extra={"pubsub_mode": mode})
        from google.cloud import pubsub_v1

        self._client = pubsub_v1.SubscriberClient()
        self._sub_path = self._client.subscription_path(self.project_id, CSV_RECEIVED_SUBSCRIPTION)
        self._require_subscription()

    def _require_subscription(self) -> None:
        """Fail loud at startup when the subscription is absent (errors, never skips).

        Provisioning is `make topics-create` (tools/local/create_topics.py) — the
        worker never creates its own subscription (no silent auto-repair).
        """
        from google.api_core.exceptions import NotFound

        try:
            self._client.get_subscription(request={"subscription": self._sub_path})
        except NotFound as exc:
            raise CsvIngestError(
                f"subscription {CSV_RECEIVED_SUBSCRIPTION!r} does not exist on project "
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
            # Deadline 0 = immediate redelivery (the emulator honours it); the
            # idempotency path absorbs the replay.
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
