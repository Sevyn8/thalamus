"""The entrypoint: build the engine and the adapter, then pull until the process ends.

TWO CONCURRENT THINGS, AND ONLY ONE OF THEM IS THE WORK. The pull loop is the service; the
/healthz server exists so Cloud Run has something to probe, because a Cloud Run SERVICE must
answer an HTTP startup probe even when its real work is entirely outbound. The health handler
reads the loop's heartbeat, so the probe reports on the loop rather than on the web server.

WHY A SERVICE AND NOT A JOB, once more where the entrypoint is: a job runs on a cadence and
exits. A sender has no cadence. It drains a queue, and a queue that is drained on a schedule is
a queue with latency equal to the schedule.
"""

from __future__ import annotations

import asyncio

import uvicorn
from axon import SendGridEmailAdapter
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from axon_sender.config import Config, load_config
from axon_sender.health import Heartbeat
from axon_sender.subscriber import Subscriber
from dis_core.logging import configure_logging, get_logger
from dis_rls import create_rls_engine

_log = get_logger("axon-sender")


def _health_app(heartbeat: Heartbeat) -> Starlette:
    """/healthz, reporting on the LOOP rather than on this server.

    A handler that returned 200 because uvicorn is running would report a hung pull loop as
    healthy for the life of the container, and the queue would grow with nothing saying so. This
    reads the beat the loop writes once per pass and answers 503 when it goes stale, so the
    Cloud Run probe restarts a process whose loop has stopped.
    """

    async def healthz(_: Request) -> JSONResponse:
        if heartbeat.is_fresh:
            return JSONResponse({"status": "ok", "loop_age_seconds": round(heartbeat.age_seconds, 1)})
        return JSONResponse(
            {
                "status": "stale",
                "loop_age_seconds": round(heartbeat.age_seconds, 1),
                "detail": "the pull loop has not completed a pass recently; it is hung or dead",
            },
            status_code=503,
        )

    return Starlette(routes=[Route("/healthz", healthz)])


async def _serve_health(app: Starlette, port: int) -> None:
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_config=None)  # noqa: S104
    await uvicorn.Server(config).serve()


async def _run(config: Config) -> None:
    # THE ONE ENGINE, and it is the SENDER's. axon_sender holds INSERT on
    # axon.platform_deliveries and nothing else: no SELECT anywhere, nothing on the tenant ledger.
    # create_rls_engine carries dis-rls's first-use posture guard, which verifies on the first use
    # that this is the expected database and that the role is NOSUPERUSER NOBYPASSRLS. The table
    # this service writes has no RLS today; the tenant ledger it will write one slice from now
    # does, and a bypassing role would defeat that isolation invisibly.
    engine = create_rls_engine(config.sender_url)
    # CONSTRUCTED ONCE, HERE, and guarded on its credential inside the constructor. An adapter
    # that constructs without a key can only fail later, with a message already in flight.
    adapter = SendGridEmailAdapter(api_key=config.sendgrid_api_key, from_email=config.sendgrid_from_email)
    subscriber = Subscriber(project_id=config.project_id, engine=engine, adapter=adapter)

    _log.info(
        "axon-sender ready",
        extra={
            "event": "axon.sender.ready",
            "write_surface": "axon.platform_deliveries (insert only)",
            "reads": "none",
        },
    )

    try:
        if config.run_health_server:
            await asyncio.gather(
                subscriber.run_forever(),
                _serve_health(_health_app(subscriber.heartbeat), config.port),
            )
        else:
            await subscriber.run_forever()
    finally:
        await engine.dispose()
        await adapter.aclose()


def main() -> int:
    configure_logging()
    asyncio.run(_run(load_config()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
