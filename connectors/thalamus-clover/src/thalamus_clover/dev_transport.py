"""The manual trigger transport (the PRODUCER): mint a stable connector_run_id, build a
ConnectorTrigger, run one OFFLINE Clover pull via run_trigger with a fake CloverApi.

This is the orchestrator role, deliberately distinct from the receiver: it STAMPS the
producer-owned identifiers (a deterministic connector_run_id and a fresh trace_id) and hands
them on the trigger; the receiver (ConnectorPipeline) reads them and mints nothing (D54).

connector_run_id is derived from the caller-supplied ``--run-key`` (the logical-run
boundary), NEVER from wall-clock: a retry reuses the same run_key (same id, dedup collapses
it); a new intended pull uses a new run_key (new id, not deduped). trace_id is minted fresh
per invocation via dis_core (the producer origin of the trace).
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from dis_core.logging import configure_logging
from dis_core.trace_id import new_trace_id
from thalamus_clover.config import CloverConfig
from thalamus_clover.fakes import FakeCloverApi, FakeSessionStore
from thalamus_clover.main import run_trigger
from thalamus_clover.pipeline import build_clover_pipeline, build_engine
from thalamus_clover.run_id import mint_connector_run_id
from thalamus_connector_sdk import SdkConfig
from thalamus_connector_sdk.adapter import Domain
from thalamus_connector_sdk.trigger import ConnectorTrigger


async def _run(args: argparse.Namespace) -> int:
    sdk_config = SdkConfig.from_env()
    clover_config = CloverConfig.from_env()

    connector_run_id = mint_connector_run_id(
        args.tenant_id, args.store_id, args.source_id, args.template_id, args.run_key
    )
    trace_id = new_trace_id()  # producer mints the trace; the receiver reads it (D54)

    trigger = ConnectorTrigger(
        schema_version=1,
        trace_id=trace_id,
        connector_run_id=connector_run_id,
        tenant_id=UUID(args.tenant_id),
        store_id=UUID(args.store_id),
        source_id=args.source_id,
        template_id=UUID(args.template_id),
        domains=[Domain.CATALOG],
        cursor=None,
        store_code=args.store_code,
    )

    engine = build_engine(sdk_config)
    try:
        pipeline = build_clover_pipeline(
            sdk_config,
            clover_config,
            engine=engine,
            token_store=FakeSessionStore(),
            api=FakeCloverApi(),
        )
        outcome = await run_trigger(pipeline, trigger)
    finally:
        await engine.dispose()

    print(f"connector_run_id={connector_run_id}")  # noqa: T201 - CLI output
    print(f"trace_id={trace_id}")  # noqa: T201
    print(f"disposition={outcome.disposition}")  # noqa: T201
    print(f"bronze_id={outcome.bronze_id}")  # noqa: T201
    print(f"next_cursor={outcome.next_cursor}")  # noqa: T201
    return 0


def main() -> int:
    configure_logging()
    parser = argparse.ArgumentParser(description="Offline Clover snapshot pull (spine transport)")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--template-id", required=True)
    parser.add_argument("--run-key", required=True, help="the producer-owned logical-run boundary")
    parser.add_argument("--store-code", default=None)
    args = parser.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    raise SystemExit(main())
