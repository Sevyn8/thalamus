"""Operator-run Clover sandbox smoke check (NOT part of the test suite).

Exercises the real ``CloverPuller`` + ``CloverAdapter`` against the live Clover SANDBOX
merchant: resolves a session from the C1 token vault, pulls the catalog, maps it, and prints
the resulting snapshot rows. This file is deliberately named without a ``test_`` prefix so
pytest never collects it; it makes real network calls and rotates a real refresh token.

NO DB, NO GCS, NO PUB/SUB. This is the C2 proof and stops at the mapped rows; the bronze
write and the ingress.ready publish are the pipeline's job and are exercised by
dev_transport / real_transport, not here.

Auth comes from the C1 vault under the operator's ADC:

    gcloud auth application-default login
    uv run python connectors/thalamus-clover/scripts/clover_sandbox_smoke.py \
        --project sevyn8-thalamus-staging

``--project`` is REQUIRED and has no default: there must be no way to point this at
production by forgetting a flag. Each run mints an access token through
``CloverTokenStore``, which rotates the stored refresh token by design (single-use).

Environment:

    CLOVER_CLIENT_ID    (required)  the Clover app id (public).
    CLOVER_APP_SECRET   (optional)  only the RECOVERY leg sends it; a plain refresh does
                                    not, so a smoke run against a healthy record needs none.
    CLOVER_API_BASE_URL (optional)  defaults to the NA sandbox host.

Exit codes: 0 on success, non-zero on any failure. NO TOKEN VALUE IS EVER PRINTED.
"""

from __future__ import annotations

import argparse
import os
import sys
from uuid import UUID

from thalamus_clover.adapter import CloverAdapter
from thalamus_clover.config import CloverConfig
from thalamus_clover.mapping import SNAPSHOT_HEADER
from thalamus_clover.puller import CloverPuller
from thalamus_clover_oauth import CloverOAuthClient, CloverTokenStore, CloverTokenVault, GoogleSecretBackend
from thalamus_connector_sdk import Domain, run_preflight
from thalamus_connector_sdk.trigger import ConnectorTrigger

# The C1-pinned sandbox target, so C2 proves the same connection C3 will deploy.
DEFAULT_TENANT_ID = "019f9d6d-c032-7e03-a232-ee77299f9b5d"  # TestCo
DEFAULT_SOURCE_ID = "clover_pos_v1"
# Placeholders: the smoke path stops before bronze, so neither is used for a write.
_SMOKE_STORE_ID = "019f9d71-b356-7caf-8c56-04e5ba6670d0"
_SMOKE_TEMPLATE_ID = "019fa1a9-51dc-77d0-bc4e-2f1088ec693d"


def main() -> int:
    parser = argparse.ArgumentParser(description="Clover SANDBOX catalog smoke pull (operator-run)")
    parser.add_argument(
        "--project",
        required=True,
        help="GCP project holding the C1 token vault. REQUIRED, no default.",
    )
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    args = parser.parse_args()

    config = CloverConfig.from_env()
    print(f"[smoke] base_url={config.base_url} project={args.project}")
    if "sandbox" not in config.base_url:
        print("[smoke] REFUSING: this smoke script is for the SANDBOX host only")
        return 2

    client_id = os.environ.get("CLOVER_CLIENT_ID")
    if not client_id:
        print("[smoke] CLOVER_CLIENT_ID is not set")
        return 2

    # client_secret is inert on the refresh leg (Clover takes client_id + refresh_token
    # only); it is passed through when present so a recovery can still succeed.
    store = CloverTokenStore(
        vault=CloverTokenVault(GoogleSecretBackend(project_id=args.project)),
        client=CloverOAuthClient(
            base_url=config.base_url,
            client_id=client_id,
            client_secret=os.environ.get("CLOVER_APP_SECRET", ""),
            redirect_uri="",
        ),
    )

    adapter = CloverAdapter(api=CloverPuller(base_url=config.base_url), token_store=store)
    trigger = ConnectorTrigger(
        schema_version=1,
        trace_id=UUID(int=0),
        connector_run_id="smoke",
        tenant_id=UUID(args.tenant_id),
        store_id=UUID(_SMOKE_STORE_ID),
        source_id=args.source_id,
        template_id=UUID(_SMOKE_TEMPLATE_ID),
        domains=[Domain.CATALOG],
        cursor=None,
    )

    try:
        auth = adapter.authenticate(trigger)
        print(
            f"[smoke] authenticate OK: merchant={auth.extra['merchant_id']} "
            f"currency={auth.extra['currency']!r} (token resolved, record rotated)"
        )
        result = adapter.extract(auth, Domain.CATALOG, None)
    except Exception as exc:  # operator-facing script: surface any failure
        print(f"[smoke] FAILED: {type(exc).__name__}: {exc}")
        detail = getattr(exc, "detail", None)
        if detail:
            print(f"[smoke] detail: {detail}")
        return 1

    print(
        f"[smoke] extract OK: {len(result.rows)} row(s), dropped={result.dropped_count} "
        f"{list(result.dropped_sample) or ''} next_cursor={result.next_cursor} "
        f"rate_limit_state={result.rate_limit_state}"
    )

    widths = {column: max(len(column), 22) for column in SNAPSHOT_HEADER}
    print("\n" + "  ".join(column.ljust(widths[column]) for column in SNAPSHOT_HEADER))
    print("  ".join("-" * widths[column] for column in SNAPSHOT_HEADER))
    for row in result.rows:
        # A column the row does not carry prints as the empty cell it will be in the CSV.
        # For stock_qty that blank is the POINT: untracked is NULL downstream, never 0.
        print("  ".join(row.values.get(column, "").ljust(widths[column]) for column in SNAPSHOT_HEADER))

    tracked = sum(1 for row in result.rows if "stock_qty" in row.values)
    print(
        f"\n[smoke] stock: {tracked} tracked / {len(result.rows) - tracked} untracked "
        "(untracked rows carry NO stock_qty key -> NULL, never 0)"
    )
    verdict = run_preflight(result)
    print(f"[smoke] preflight: ok={verdict.ok} rows={verdict.row_count} columns={len(verdict.columns)}")
    return 0 if verdict.ok else 1


if __name__ == "__main__":
    sys.exit(main())
