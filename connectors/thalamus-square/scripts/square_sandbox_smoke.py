"""Operator-run Square sandbox smoke check (NOT part of the test suite).

Exercises the real ``SquarePuller`` transport against a live Square SANDBOX seller: lists
locations, pulls one catalog page, and prints counts. This file is deliberately named
without a ``test_`` prefix so pytest never collects it; it makes real network calls and
needs a real sandbox access token.

Run it (from anywhere; uses the workspace venv):

    uv run python connectors/thalamus-square/scripts/square_sandbox_smoke.py

Environment variables:

    SQUARE_ACCESS_TOKEN   (required)  A Square SANDBOX access token for a test seller.
                                      Sandbox tokens only; never a production token.
    SQUARE_API_BASE_URL   (optional)  Defaults to the sandbox host
                                      (https://connect.squareupsandbox.com).
    SQUARE_API_VERSION    (optional)  Defaults to the pinned Square-Version constant.

Exit codes: 0 on success, non-zero on any failure (missing token, HTTP error, transport
error). Prints a short summary line per step.
"""

from __future__ import annotations

import sys
from uuid import uuid4

from thalamus_square.auth import EnvTokenStore
from thalamus_square.config import SquareConfig
from thalamus_square.puller import SquarePuller


def main() -> int:
    config = SquareConfig.from_env()
    print(f"[smoke] base_url={config.base_url} square_version={config.api_version}")

    try:
        # EnvTokenStore reads SQUARE_ACCESS_TOKEN; a missing token raises ConnectorAuthError.
        # tenant/source are irrelevant for the single-token env store; use throwaway values.
        token = EnvTokenStore().get_token(uuid4(), "sandbox-smoke")
    except Exception as exc:  # operator-facing script: surface any startup failure
        print(f"[smoke] FAILED to resolve access token: {type(exc).__name__}: {exc}")
        return 1

    puller = SquarePuller(base_url=config.base_url, api_version=config.api_version)

    try:
        locations = puller.list_locations(token)
        print(f"[smoke] list_locations OK: {len(locations)} location(s)")

        page = puller.list_catalog(token, cursor=None)
        print(
            f"[smoke] list_catalog OK: {len(page.items)} item(s), "
            f"{len(page.categories)} category(ies), next_cursor={'yes' if page.next_cursor else 'no'}"
        )
    except Exception as exc:  # operator-facing script: any failure is a non-zero exit
        print(f"[smoke] FAILED during Square calls: {type(exc).__name__}: {exc}")
        return 1

    print("[smoke] PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
