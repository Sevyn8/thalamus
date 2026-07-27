"""Entrypoint: resolve config, build the wired pipeline, run triggers.

Mirrors the Square connector's main shape (config resolve, engine own-and-dispose, exit
codes). The trigger TRANSPORT is the orchestrator's concern; ``run_trigger`` is the seam
transport calls once a trigger is in hand. ``main`` validates wiring and is the deploy
healthcheck.
"""

from __future__ import annotations

import asyncio

from dis_core.logging import configure_logging, get_logger
from thalamus_clover.config import SERVICE_NAME, CloverConfig
from thalamus_clover.pipeline import build_clover_pipeline, build_engine
from thalamus_connector_sdk import ConnectorConfigError, ConnectorOutcome, ConnectorPipeline, SdkConfig
from thalamus_connector_sdk.trigger import ConnectorTrigger

EXIT_OK = 0
EXIT_CONFIG = 2

_log = get_logger(SERVICE_NAME)


async def run_trigger(pipeline: ConnectorPipeline, trigger: ConnectorTrigger) -> ConnectorOutcome:
    """Run one trigger through the pipeline (the seam the transport calls)."""
    return await pipeline.run(trigger)


async def _run() -> int:
    config = SdkConfig.from_env()
    clover_config = CloverConfig.from_env()
    engine = build_engine(config)
    try:
        build_clover_pipeline(config, clover_config, engine=engine)
        _log.bind(stage="startup").info(
            "clover connector wired; awaiting trigger transport (orchestrator-owned)"
        )
    finally:
        await engine.dispose()
    return EXIT_OK


def main() -> int:
    configure_logging()
    try:
        return asyncio.run(_run())
    except ConnectorConfigError as exc:
        _log.bind(stage="startup").error("configuration error; exiting: %s", exc)
        return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
