"""``python -m synapse.orchestrator`` — the entrypoint, hand-run and scheduled alike.

D3: A COMPONENT WHOSE ONLY EXECUTION PATH IS A CRON NOBODY CAN INVOKE IS UNTESTABLE. This
existed before any schedule did, and the schedule when it arrived changed nothing about what
runs: the container's ENTRYPOINT *is* this module, so Cloud Scheduler is simply a second caller.
A scheduled execution supplies no arguments and gets the full sweep; an operator supplies
`--dry-run` or `--tenant` through `gcloud run jobs execute --args`. The connectors set that
precedent: their images carry no default args and every execution supplies them, so the
hand-run and the real run cannot drift.

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
from datetime import UTC, datetime
from uuid import UUID

from dis_core.logging import configure_logging, get_logger
from dis_rls import create_rls_engine
from synapse.core.errors import SynapseError
from synapse.orchestrator.freshness import emit_tenant_freshness, tenant_freshness
from synapse.orchestrator.runner import SlotResult, run_due, summarise
from synapse.persistence.provision_postgres import PostgresProvisionReader
from synapse.registry import max_rungs

# STRUCTURED, BECAUSE NOTHING HERE SELF-HEALS. `print()` reaches Cloud Logging with no
# `severity`, so every line files at DEFAULT and no log-based alert can match one — the failure
# is legible to a human reading logs and invisible to a matcher.
#
# That would be a nuisance for a component that recovers on its own. This one does not: a run
# recorded `failed` is TERMINAL, `claim()` skips it, and tomorrow is a different slot — so a
# failed slot stays failed forever and only a human clears it. A system with no self-healing
# needs its failures matchable rather than merely readable.
#
# dis_core.logging renames `levelname` to `severity` for exactly this reason (see its module
# comment), so this is the project's existing convention rather than a new one.
#
# ONE OUTPUT PATH, not two. A human-readable report alongside the structured one would be two
# representations of the same events, free to drift; a hand-run reads the JSON, which carries
# the full content.
_log = get_logger("synapse-orchestrator")


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
    """One structured entry per pair, plus a summary. Severity is the point.

    ERROR for a failed run, WARNING for a takeover (the only visible evidence a previous
    execution died), INFO for everything else. An alert matches on severity; a human reads the
    same lines.
    """
    if not results:
        _log.info(
            "no provisioned pair was due",
            extra={"dry_run": dry_run, "due": 0, "hint": "synapse.provision may be empty"},
        )
        return

    for result in sorted(results, key=lambda r: (r.analysis_id, str(r.tenant_id))):
        fields = {
            "dry_run": dry_run,
            "analysis_id": result.analysis_id,
            "tenant_id": str(result.tenant_id),
            "slot": result.slot.isoformat(),
            "outcome": result.outcome,
            "skipped": result.skipped,
            "taken_over": result.taken_over,
            "actions_proposed": result.actions_proposed,
            "actions_appended": result.actions_appended,
            "detail": result.detail,
        }
        state = "skipped" if result.skipped else str(result.outcome)
        message = f"{result.analysis_id} {result.tenant_id} slot={result.slot} {state}"
        if result.failed:
            _log.error(message, extra=fields)
        elif result.taken_over:
            _log.warning(f"{message} (took over a crashed attempt)", extra=fields)
        else:
            _log.info(message, extra=fields)

    counts = dict(sorted(summarise(results).items()))
    _log.info("sweep complete", extra={"dry_run": dry_run, "counts": counts})


async def _main(argv: list[str] | None = None) -> int:
    # Installs the JSON handler that renames levelname -> severity. WITHOUT THIS the logger
    # falls back to the root logger's default: plain text, WARNING threshold, so every INFO line
    # vanishes and nothing carries a severity Cloud Logging can read. Same call, same place, as
    # streaming-consumer's and dis-ui-server's main().
    configure_logging()
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
        # FRESHNESS, INSIDE THE try BECAUSE THE finally DISPOSES THE READER. Emitted after the
        # sweep so a freshness problem can never affect what the sweep does, and emitted for
        # EVERY provisioned tenant — including healthy ones — because a signal that is absent
        # when things are good cannot be thresholded.
        #
        # A SECOND READ OF THE PROVISION TABLE, not a second read per tenant. run_due does not
        # return the provisions and threading them out would change its signature for an
        # observation concern. One PLATFORM read of a table with two rows.
        #
        # min(), not last-wins: for a tenant that has never sold, the age is how long we have
        # been watching, so the EARLIEST enablement is the honest start.
        try:
            enabled_at: dict[UUID, datetime] = {}
            for provision in await PostgresProvisionReader(reader).active(max_rungs=max_rungs()):
                previous = enabled_at.get(provision.tenant_id)
                if previous is None or provision.enabled_at < previous:
                    enabled_at[provision.tenant_id] = provision.enabled_at
            emit_tenant_freshness(await tenant_freshness(reader, enabled_at=enabled_at, now=now))
        except Exception as exc:  # noqa: BLE001 - observation must not fail the sweep
            # NOT RE-RAISED: the sweep's real work (claiming runs, appending actions) has already
            # succeeded by here, and failing the execution would misreport that.
            #
            # AND NOT ALERTED DIRECTLY, which is deliberate rather than an omission. This line
            # carries no `outcome` field, so it does not match the failed-slot policy — whose
            # action is "re-run the slot by hand" and would be wrong here. The freshness policy
            # covers it instead: its evaluationMissingData is set to treat NO DATA as a breach,
            # so if this emission stops the freshness alert fires on the silence. The absence of
            # the absence-signal is caught by configuration rather than by a seventh alert.
            _log.error(
                f"tenant freshness could not be emitted: {type(exc).__name__}: {exc}",
                extra={"error_type": type(exc).__name__},
            )
    except SynapseError as exc:
        _log.error(
            f"the sweep could not start: {type(exc).__name__}: {exc}",
            extra={"error_type": type(exc).__name__},
        )
        return 2
    finally:
        await reader.dispose()
        await writer.dispose()

    _report(results, dry_run=args.dry_run)
    return 1 if any(result.failed for result in results) else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
