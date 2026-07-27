"""Environment-resolved OAuth profile for the production Clover token store.

Kept in the CONNECTOR, not in ``thalamus-clover-oauth``: that package is deliberately
SDK-free and env-free so the BFF can construct its own client however it likes. The
connector's deployment env is the connector's business.

``client_id`` / ``client_secret`` / the Secret Manager project are REQUIRED (no silent
fallback, code-quality rule 4): a missing one raises ``ConnectorConfigError`` at connector
startup.

``client_secret`` is required even though the REFRESH leg does not send one, because the
RECOVERY leg (D4) does, and recovery is the path that saves a merchant after a lost write.
Starting without it would work for weeks and then fail exactly when it matters most.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import timedelta

from thalamus_connector_sdk.errors import ConnectorConfigError

_CLOVER_CLIENT_ID = "CLOVER_CLIENT_ID"
_CLOVER_APP_SECRET = "CLOVER_APP_SECRET"
_CLOVER_SECRETS_PROJECT_ID = "CLOVER_SECRETS_PROJECT_ID"
_CLOVER_OAUTH_REFRESH_SKEW_SECONDS = "CLOVER_OAUTH_REFRESH_SKEW_SECONDS"

# Clover access tokens live 30 MINUTES (measured against the live sandbox), so the default
# skew is minutes rather than the Square lane's days.
DEFAULT_REFRESH_SKEW_SECONDS = 5 * 60


@dataclass(frozen=True)
class CloverOAuthEnv:
    """Resolved OAuth profile for the production token store."""

    client_id: str
    client_secret: str
    secrets_project_id: str
    refresh_skew: timedelta

    @classmethod
    def from_env(cls) -> CloverOAuthEnv:
        client_id = os.environ.get(_CLOVER_CLIENT_ID)
        if not client_id:
            raise ConnectorConfigError(f"{_CLOVER_CLIENT_ID} is not set; cannot refresh Clover OAuth tokens")
        client_secret = os.environ.get(_CLOVER_APP_SECRET)
        if not client_secret:
            raise ConnectorConfigError(
                f"{_CLOVER_APP_SECRET} is not set; the recovery leg needs it (refresh does not)"
            )
        secrets_project_id = os.environ.get(_CLOVER_SECRETS_PROJECT_ID)
        if not secrets_project_id:
            raise ConnectorConfigError(
                f"{_CLOVER_SECRETS_PROJECT_ID} is not set; cannot reach the Secret Manager token vault"
            )
        raw_skew = os.environ.get(_CLOVER_OAUTH_REFRESH_SKEW_SECONDS)
        seconds = float(raw_skew) if raw_skew else float(DEFAULT_REFRESH_SKEW_SECONDS)
        return cls(
            client_id=client_id,
            client_secret=client_secret,
            secrets_project_id=secrets_project_id,
            refresh_skew=timedelta(seconds=seconds),
        )
