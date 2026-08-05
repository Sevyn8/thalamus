"""``python -m synapse.orchestrator`` — the hand-run entrypoint.

D3: A COMPONENT WHOSE ONLY EXECUTION PATH IS A CRON NOBODY CAN INVOKE IS UNTESTABLE. This exists
before any schedule does, and it is the same code path a scheduled execution takes — the
container's ENTRYPOINT will be this module, so a scheduler adds a caller and changes nothing
about what runs. The connectors set that precedent: their images carry no default args and every
execution supplies them, so the hand-run and the real run cannot drift.

    # against the local devbox, writing nothing
    python -m synapse.orchestrator --dry-run

    # one pair, for real
    SYNAPSE_READER_URL=... SYNAPSE_WRITER_URL=... \\
      python -m synapse.orchestrator --tenant <uuid> --analysis dead_stock

    # what the sweep would have done on a past day
    python -m synapse.orchestrator --now 2026-07-01T09:00:00+05:30 --dry-run

EXIT CODES, because a scheduler reads them and a human reads the summary:
    0  every due pair ran or was legitimately skipped
    1  at least one run recorded 'failed'
    2  the sweep could not start — bad DSN, refused provision table, unusable arguments

TWO DSNs, NOT ONE, and passing the same value for both is a real mistake rather than a shortcut:
the reader is ``synapse_reader`` (SELECT on two canonical tables, the action log, provision and
run) and the writer is ``synapse_writer`` (INSERT on the log, the run state machine, and nothing
on canonical). Handing the writer's DSN to the reader would fail on the first canonical read;
handing the reader's to the writer would fail on the first append. Both fail loudly, which is
the point of the split being grants rather than discipline.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import UTC, datetime
from uuid import UUID

from dis_rls import create_rls_engine
from synapse.core.errors import SynapseError
from synapse.orchestrator.runner import SlotResult, run_due, summarise


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m synapse.orchestrator",
        description="Run every provisioned analysis that is due. Shadow only: nothing is delivered anywhere.",
    )
    parser.add_argument(
        "--reader-dsn",
        default=os.environ.get("SYNAPSE_READER_URL"),
        help="synapse_reader DSN. Defaults to $SYNAPSE_READER_URL.",
    )
    parser.add_argument(
        "--writer-dsn",
        default=os.environ.get("SYNAPSE_WRITER_URL"),
        help="synapse_writer DSN. Defaults to $SYNAPSE_WRITER_URL. Not needed with --dry-run.",
    )
    parser.add_argument(
        "--now",
        default=None,
        help=(
            "ISO-8601 instant, MUST carry an offset (e.g. 2026-07-01T09:00:00+05:30). Defaults "
            "to the current UTC instant. The slot is floored from this in each tenant's own "
            "reporting timezone, so this is not itself the slot."
        ),
    )
    parser.add_argument("--tenant", default=None, help="Only this tenant id.")
    parser.add_argument("--analysis", default=None, help="Only this analysis id.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Resolve, evaluate and propose, and write NOTHING: no run claimed, no action "
        "appended. The right way to run this the first time.",
    )
    return parser


def _instant(raw: str | None) -> datetime:
    """Parse ``--now``, refusing a naive value.

    A naive instant would be silently treated as UTC by most of the stdlib and would shift every
    tenant's slot by their offset — the exact failure ``slot_for`` refuses. Rejected here too so
    the message names the argument rather than surfacing from three frames down.
    """
    if raw is None:
        return datetime.now(UTC)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise SystemExit(f"--now {raw!r} is not ISO-8601: {exc}") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise SystemExit(
            f"--now {raw!r} has no UTC offset. Add one (…+05:30, or …Z): a naive instant would "
            "shift every tenant's slot by their own offset, silently"
        )
    return parsed


def _report(results: tuple[SlotResult, ...], *, dry_run: bool) -> None:
    prefix = "DRY RUN, nothing written — " if dry_run else ""
    if not results:
        print(f"{prefix}no provisioned pair was due. synapse.provision may be empty.")
        return
    for result in sorted(results, key=lambda r: (r.analysis_id, str(r.tenant_id))):
        state = "skipped" if result.skipped else str(result.outcome)
        marks = " [took over a crashed attempt]" if result.taken_over else ""
        print(
            f"{result.analysis_id} {result.tenant_id} slot={result.slot} {state}"
            f" proposed={result.actions_proposed} appended={result.actions_appended}{marks}"
        )
        if result.detail:
            print(f"    {result.detail}")
    print(f"{prefix}{dict(sorted(summarise(results).items()))}")


async def _main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if not args.reader_dsn:
        raise SystemExit("no reader DSN: pass --reader-dsn or set SYNAPSE_READER_URL")
    if not args.dry_run and not args.writer_dsn:
        raise SystemExit(
            "no writer DSN: pass --writer-dsn or set SYNAPSE_WRITER_URL. Use --dry-run to run "
            "without writing anything"
        )

    now = _instant(args.now)
    tenant = UUID(args.tenant) if args.tenant else None

    reader = create_rls_engine(args.reader_dsn)
    # In a dry run nothing is written, but run_due still constructs the recorder and appender, so
    # an engine must exist. The READER's DSN is used deliberately: if a dry run ever attempted a
    # write despite the flag, synapse_reader's grants would refuse it. The flag says it will not
    # write; the credential makes that true.
    writer = create_rls_engine(args.writer_dsn if not args.dry_run else args.reader_dsn)
    try:
        results = tuple(
            await run_due(
                reader_engine=reader,
                writer_engine=writer,
                now=now,
                dry_run=args.dry_run,
                only_tenant=tenant,
                only_analysis=args.analysis,
            )
        )
    except SynapseError as exc:
        print(f"the sweep could not start: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2
    finally:
        await reader.dispose()
        await writer.dispose()

    _report(results, dry_run=args.dry_run)
    return 1 if any(result.failed for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
