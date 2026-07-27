"""The REAL trigger transport (the PRODUCER): mint a stable connector_run_id, build a
ConnectorTrigger, run one LIVE Clover pull via run_trigger against the real Clover API.

Structurally identical to ``dev_transport`` with ONE deliberate difference: it injects
nothing into :func:`build_clover_pipeline`, so that function's own defaults resolve - the
httpx ``CloverPuller`` and the Secret Manager-backed ``CloverTokenStore``. That single
omission IS the offline/online switch, which is why ``tests/unit/test_transport.py``
asserts the call site by AST: a future edit that re-injects a fake fails loudly instead of
silently shipping an offline image.

The producer/receiver split is unchanged (D54): this module STAMPS the producer-owned
identifiers and hands them on the trigger; the receiver reads them and mints nothing.

``mint_connector_run_id`` is REUSED from ``dev_transport``, never copied, so the offline and
online paths cannot drift on the dedup id.

Run as ``python -m thalamus_clover.real_transport`` - there is no console script, the repo
has none.
"""

from __future__ import annotations

import argparse
import asyncio
from uuid import UUID

from dis_core.logging import configure_logging, get_logger
from dis_core.trace_id import new_trace_id
from thalamus_clover.config import SERVICE_NAME, CloverConfig
from thalamus_clover.dev_transport import mint_connector_run_id
from thalamus_clover.main import EXIT_CONFIG, run_trigger
from thalamus_clover.pipeline import build_clover_pipeline, build_engine
from thalamus_connector_sdk import ConnectorConfigError, SdkConfig
from thalamus_connector_sdk.adapter import Domain
from thalamus_connector_sdk.trigger import ConnectorTrigger

_log = get_logger(SERVICE_NAME)


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
        # NEITHER token_store NOR api: the defaults resolve (CloverPuller + CloverTokenStore).
        pipeline = build_clover_pipeline(sdk_config, clover_config, engine=engine)
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
    parser = argparse.ArgumentParser(description="Live Clover snapshot pull (real transport)")
    parser.add_argument("--tenant-id", required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--source-id", required=True)
    parser.add_argument("--template-id", required=True)
    parser.add_argument("--run-key", required=True, help="the producer-owned logical-run boundary")
    parser.add_argument("--store-code", default=None)
    args = parser.parse_args()
    try:
        return asyncio.run(_run(args))
    except ConnectorConfigError as exc:
        _log.bind(stage="startup").error("configuration error; exiting: %s", exc)
        return EXIT_CONFIG


if __name__ == "__main__":
    raise SystemExit(main())
