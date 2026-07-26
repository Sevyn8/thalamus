"""Environment-resolved Square configuration (WorkerConfig.from_env pattern).

- ``SQUARE_API_BASE_URL`` - the Square API base. Defaults to the SANDBOX host; a legit
  optional with a default (v1 targets sandbox), not a rule-4 silent fallback for a
  required value.
- ``SQUARE_API_VERSION`` - the ``Square-Version`` header; defaults to a pinned version.

The per-tenant access token is NOT env config: it comes from a token store (auth.py),
resolved per trigger tenant.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from thalamus_connector_sdk.errors import ConnectorConfigError

_SQUARE_API_BASE_URL = "SQUARE_API_BASE_URL"
_SQUARE_API_VERSION = "SQUARE_API_VERSION"
_SQUARE_CLIENT_ID = "SQUARE_CLIENT_ID"
_SQUARE_APP_SECRET = "SQUARE_APP_SECRET"
_SQUARE_SECRETS_PROJECT_ID = "SQUARE_SECRETS_PROJECT_ID"
_SQUARE_OAUTH_REFRESH_SKEW_SECONDS = "SQUARE_OAUTH_REFRESH_SKEW_SECONDS"

SANDBOX_BASE_URL = "https://connect.squareupsandbox.com"

# Refresh an access token this many seconds before its expiry by default (3 days). Square
# access tokens live ~30 days, so any daily-ish connector run always holds a fresh token.
DEFAULT_REFRESH_SKEW_SECONDS = 3 * 24 * 60 * 60

# Pinned Square-Version header. Upgrade policy: Square dates API versions and supports
# each for roughly a year past release; a pinned version keeps request/response shapes
# stable across our deploys (Square applies the pinned version, not "latest"). Bump this
# to a current stable version deliberately (read Square's API changelog first, then
# re-run the sandbox smoke script), never silently. 2026-01-22 is the current stable
# version as of this pin.
DEFAULT_API_VERSION = "2026-01-22"

SERVICE_NAME = "thalamus-square"


@dataclass(frozen=True)
class SquareConfig:
    """Resolved Square API profile."""

    base_url: str
    api_version: str

    @classmethod
    def from_env(cls) -> SquareConfig:
        return cls(
            base_url=os.environ.get(_SQUARE_API_BASE_URL, SANDBOX_BASE_URL),
            api_version=os.environ.get(_SQUARE_API_VERSION, DEFAULT_API_VERSION),
        )


@dataclass(frozen=True)
class SquareOAuthConfig:
    """Resolved OAuth profile for the production token vault (S2).

    The OAuth host is the same Square host as the API (``SQUARE_API_BASE_URL``), so it is not
    a separate env var; ``environment`` (sandbox vs production, stamped onto stored token
    sets) is derived from that host. ``client_id`` / ``client_secret`` / the Secret Manager
    project are REQUIRED (no silent fallback, code-quality rule 4): a missing one raises
    ``ConnectorConfigError`` at connector startup. The connector only ever refreshes, so no
    redirect URI is needed here (that is the BFF's connect concern).
    """

    client_id: str
    client_secret: str
    secrets_project_id: str
    oauth_base_url: str
    environment: str
    refresh_skew_seconds: float

    @classmethod
    def from_env(cls) -> SquareOAuthConfig:
        client_id = os.environ.get(_SQUARE_CLIENT_ID)
        if not client_id:
            raise ConnectorConfigError(f"{_SQUARE_CLIENT_ID} is not set; cannot refresh Square OAuth tokens")
        client_secret = os.environ.get(_SQUARE_APP_SECRET)
        if not client_secret:
            raise ConnectorConfigError(f"{_SQUARE_APP_SECRET} is not set; cannot refresh Square OAuth tokens")
        secrets_project_id = os.environ.get(_SQUARE_SECRETS_PROJECT_ID)
        if not secrets_project_id:
            raise ConnectorConfigError(
                f"{_SQUARE_SECRETS_PROJECT_ID} is not set; cannot reach the Secret Manager token vault"
            )
        oauth_base_url = os.environ.get(_SQUARE_API_BASE_URL, SANDBOX_BASE_URL)
        environment = "sandbox" if "squareupsandbox" in oauth_base_url else "production"
        raw_skew = os.environ.get(_SQUARE_OAUTH_REFRESH_SKEW_SECONDS)
        refresh_skew_seconds = float(raw_skew) if raw_skew else float(DEFAULT_REFRESH_SKEW_SECONDS)
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            secrets_project_id=secrets_project_id,
            oauth_base_url=oauth_base_url,
            environment=environment,
            refresh_skew_seconds=refresh_skew_seconds,
        )
