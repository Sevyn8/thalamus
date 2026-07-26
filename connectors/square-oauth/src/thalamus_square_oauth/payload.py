"""The Square OAuth token set persisted as one Secret Manager secret version.

Serialized as compact JSON. This is credential material (access + refresh tokens): it is
NEVER logged, echoed in an error, or placed in audit context.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta


def _parse_rfc3339(value: str) -> datetime:
    """Parse a Square RFC3339 timestamp (``...Z`` or explicit offset) to an aware datetime."""
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class SquareTokenSet:
    """The stored OAuth credential set for one tenant/source."""

    access_token: str
    refresh_token: str
    expires_at: str  # RFC3339 access-token expiry, verbatim from Square
    merchant_id: str
    token_type: str
    scopes: tuple[str, ...]
    obtained_at: str  # RFC3339, when this version was stored/rotated by us
    environment: str  # "sandbox" | "production"

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at,
                "merchant_id": self.merchant_id,
                "token_type": self.token_type,
                "scopes": list(self.scopes),
                "obtained_at": self.obtained_at,
                "environment": self.environment,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str) -> SquareTokenSet:
        data = json.loads(raw)
        scopes: Sequence[object] = data["scopes"]
        return cls(
            access_token=str(data["access_token"]),
            refresh_token=str(data["refresh_token"]),
            expires_at=str(data["expires_at"]),
            merchant_id=str(data["merchant_id"]),
            token_type=str(data["token_type"]),
            scopes=tuple(str(s) for s in scopes),
            obtained_at=str(data["obtained_at"]),
            environment=str(data["environment"]),
        )

    def needs_refresh(self, *, now: datetime, skew: timedelta) -> bool:
        """True when the access token is at or past (expiry - skew) and should be refreshed
        before use. ``now`` is injected so callers/tests control the clock."""
        return now >= _parse_rfc3339(self.expires_at) - skew
