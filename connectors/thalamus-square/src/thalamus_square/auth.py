"""Per-tenant Square OAuth token resolution.

``TokenStore`` is the seam that yields a tenant's Square access token (production: the
OAuth token vault / config store; tests inject a fake). ``EnvTokenStore`` is the local
dev fallback reading a single ``SQUARE_ACCESS_TOKEN``. The token is credential material:
never logged, never placed in audit or error context.
"""

from __future__ import annotations

import os
from typing import Protocol
from uuid import UUID

from thalamus_connector_sdk import ConnectorAuthError, ConnectorReasonCode

_SQUARE_ACCESS_TOKEN = "SQUARE_ACCESS_TOKEN"


class TokenStore(Protocol):
    """Yields a tenant's Square access token, or raises ``ConnectorAuthError``."""

    def get_token(self, tenant_id: UUID) -> str: ...


class EnvTokenStore:
    """Local dev: a single ``SQUARE_ACCESS_TOKEN`` for every tenant (sandbox only)."""

    def get_token(self, tenant_id: UUID) -> str:
        token = os.environ.get(_SQUARE_ACCESS_TOKEN)
        if not token:
            raise ConnectorAuthError(
                f"{_SQUARE_ACCESS_TOKEN} is not set; cannot authenticate to Square",
                reason=ConnectorReasonCode.AUTH_FAILED,
                tenant_id=str(tenant_id),
            )
        return token
