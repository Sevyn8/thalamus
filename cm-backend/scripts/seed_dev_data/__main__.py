"""Dev seed loader entry point.

Usage:
    uv run python -m scripts.seed_dev_data [--reset] [--dry-run] [--sheets sheet1,sheet2]

=================================================================================================
TWO GUARDS, AND THE CONNECTION ONE IS THE LOAD-BEARING ONE
=================================================================================================
``--reset`` TRUNCATEs 19 tables including tenants, tenant_users, platform_users, roles,
permissions, stores, org_nodes and both audit ledgers. Against staging that is the estate.

THE ENVIRONMENT CHECK CANNOT CATCH THAT, AND THE REASON IS THE WHOLE POINT. ENVIRONMENT and
DATABASE_URL are independent values read from the same .env. The case that destroys staging is a
developer holding staging's connection string with ENVIRONMENT=local, and an environment check
passes cleanly in exactly that case. It is kept as a second condition because it costs nothing,
never as the only one.

So the real guard asserts the CONNECTION TARGET. Only loopback is allowed. Staging's Cloud SQL is
a private IP (10.55.0.3) and the Cloud SQL socket form parses to host=None, so both are refused by
construction rather than by a list of forbidden things that somebody has to keep current.

IT GUARDS THE WHOLE SCRIPT, NOT ONLY ``--reset``. A plain run inserts rather than truncates, which
is not destructive and is not harmless: one email is one identity across this platform, and
staging has already been contaminated once by seed identities. The tool has no legitimate remote
use, so there is nothing to weigh against refusing.

FAIL CLOSED. A URL this cannot parse is a URL it refuses. The refusal names the host and never
prints the URL, which carries a password.
"""
import argparse
import asyncio
import sys

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from admin_backend.config import get_settings

# The only hosts this tool may write to. Not a denylist: a denylist of remote hosts is a list
# somebody has to keep current, and the one it misses is the one that matters.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


def _refuse_non_loopback_database(database_url: str) -> str | None:
    """Return a refusal message, or None when the target is loopback.

    Parsed with SQLAlchemy's own ``make_url`` rather than a regex, so this reads the SAME target
    ``create_async_engine`` will open rather than a second derivation of it that can disagree.
    """
    try:
        host = make_url(database_url).host
    except (ArgumentError, ValueError):
        # Unparseable is refused, not waved through. A guard that cannot read its input has not
        # checked anything, and passing here would be the vacuous case.
        return (
            "DATABASE_URL could not be parsed, so the seed loader cannot tell what it would "
            "write to. Refusing."
        )

    if host is None:
        # The Cloud SQL socket form (host=/cloudsql/...) parses to no host at all. It is by
        # definition not a local Postgres, so it is refused here rather than falling through.
        return (
            "DATABASE_URL names no TCP host, which is the Cloud SQL socket form. The seed "
            "loader is a local dev tool and refuses to run against a managed database."
        )

    if host not in _LOOPBACK_HOSTS:
        return (
            f"DATABASE_URL points at {host!r}, which is not loopback. The seed loader "
            f"TRUNCATEs and rewrites the whole seed set and refuses to run against anything "
            f"but a local database. Allowed hosts: {', '.join(sorted(_LOOPBACK_HOSTS))}."
        )

    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Load dev seed data from Excel into Postgres.",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help=(
            "TRUNCATE seed tables before insert (in reverse-FK order). "
            "Destructive."
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Read and validate the Excel; do not write to the DB.",
    )
    parser.add_argument(
        "--sheets",
        type=str,
        default=None,
        help=(
            "Comma-separated sheet names to load (default: all loadable "
            "sheets)."
        ),
    )
    args = parser.parse_args()

    settings = get_settings()

    # THE CONNECTION TARGET FIRST, because it is the condition the environment label cannot
    # express. See the module docstring for why the order matters rather than being tidy.
    refusal = _refuse_non_loopback_database(settings.database_url)
    if refusal is not None:
        print(f"ERROR: {refusal}", file=sys.stderr)
        return 2

    # SECOND CONDITION, NOT THE ONLY ONE. Kept because it costs nothing and catches a
    # production label pointed at a local database, which the check above would allow.
    if settings.environment == "production":
        print(
            "ERROR: seed loader refuses to run with "
            "ENVIRONMENT=production. This script is for dev/local use "
            "only.",
            file=sys.stderr,
        )
        return 2

    from scripts.seed_dev_data.runner import run_seed
    return asyncio.run(
        run_seed(
            reset=args.reset,
            dry_run=args.dry_run,
            sheets=(
                args.sheets.split(",") if args.sheets else None
            ),
        )
    )


if __name__ == "__main__":
    sys.exit(main())
