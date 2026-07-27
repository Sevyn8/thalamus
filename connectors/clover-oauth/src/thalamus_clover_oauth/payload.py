"""The Clover OAuth token record persisted as one Secret Manager secret version.

Serialized as compact JSON. This is credential material (access + refresh + the previous
refresh token): NEVER logged, echoed in an error, or placed in audit context.

TWO DELIBERATE DIVERGENCES FROM ``thalamus_square_oauth.payload``:

1. EXPIRIES ARE UNIX TIMESTAMPS (ints), not RFC3339 strings. Clover's token endpoints
   return ``access_token_expiration`` / ``refresh_token_expiration`` as integer epoch
   seconds. They are stored verbatim rather than converted, so the record round-trips what
   the vendor actually said and no parse can drift.

2. ``previous_refresh_token`` IS NOT HISTORY. Clover refresh tokens are single-use: each
   refresh returns a new pair and kills the one just spent. The token immediately preceding
   the current one stays valid as a RECOVERY credential for roughly two weeks
   (``/oauth/v2/recovery``), and it is the only thing standing between a lost write and a
   merchant that must re-consent. It is live credential material with a shorter fuse, not a
   log line.

Note that ``previous_refresh_token`` lives INSIDE this payload — i.e. inside the CURRENT
secret version — not in a superseded version. That is what makes the D5 version prune safe:
destroying old versions cannot destroy the recovery credential.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta

# Measured against the live sandbox (2026-07-27): the access token expiry came back at
# exactly 30 minutes, the refresh token at 1 year. Documentation for whoever picks a skew;
# nothing reads them.
ACCESS_TOKEN_LIFETIME_SECONDS = 30 * 60
REFRESH_TOKEN_LIFETIME_SECONDS = 365 * 24 * 60 * 60


@dataclass(frozen=True)
class CloverTokenSet:
    """The stored OAuth credential record for one tenant/source (D1)."""

    access_token: str
    access_token_expiration: int  # unix epoch seconds, verbatim from Clover
    refresh_token: str
    refresh_token_expiration: int  # unix epoch seconds, verbatim from Clover
    # The refresh token this one replaced: a LIVE ~2-week recovery credential (see header).
    # None only on the very first record, straight out of the code exchange.
    previous_refresh_token: str | None
    previous_rotated_at: int | None  # unix epoch seconds; when previous_refresh_token was spent
    # Identity comes from the OAUTH CALLBACK query params, not from any token response, so
    # it is carried forward across every rotation rather than re-read from the vendor.
    merchant_id: str
    employee_id: str | None
    obtained_at: int  # unix epoch seconds; when WE stored/rotated this record
    environment: str  # "sandbox" | "production"

    def to_json(self) -> str:
        return json.dumps(
            {
                "access_token": self.access_token,
                "access_token_expiration": self.access_token_expiration,
                "refresh_token": self.refresh_token,
                "refresh_token_expiration": self.refresh_token_expiration,
                "previous_refresh_token": self.previous_refresh_token,
                "previous_rotated_at": self.previous_rotated_at,
                "merchant_id": self.merchant_id,
                "employee_id": self.employee_id,
                "obtained_at": self.obtained_at,
                "environment": self.environment,
            },
            separators=(",", ":"),
            sort_keys=True,
        )

    @classmethod
    def from_json(cls, raw: str) -> CloverTokenSet:
        data = json.loads(raw)
        previous = data.get("previous_refresh_token")
        rotated = data.get("previous_rotated_at")
        employee = data.get("employee_id")
        return cls(
            access_token=str(data["access_token"]),
            access_token_expiration=int(data["access_token_expiration"]),
            refresh_token=str(data["refresh_token"]),
            refresh_token_expiration=int(data["refresh_token_expiration"]),
            previous_refresh_token=None if previous is None else str(previous),
            previous_rotated_at=None if rotated is None else int(rotated),
            merchant_id=str(data["merchant_id"]),
            employee_id=None if employee is None else str(employee),
            obtained_at=int(data["obtained_at"]),
            environment=str(data["environment"]),
        )

    def needs_refresh(self, *, now: datetime, skew: timedelta) -> bool:
        """True when the access token is at or past (expiry - skew) and must be rotated
        before use. ``now`` is injected so callers/tests control the clock."""
        return now.timestamp() >= self.access_token_expiration - skew.total_seconds()

    def refresh_token_expired(self, *, now: datetime) -> bool:
        """True when the refresh token itself is past its (~1 year) expiry.

        Checked BEFORE the network call: once this is true neither the refresh leg nor the
        recovery leg can succeed (the previous token is strictly older), so the store fails
        fast with the terminal re-consent error instead of burning two doomed requests.

        Observed (2026-07-27): ``refresh_token_expiration`` moves forward ~1 year on every
        rotation, so an actively-refreshing connector never approaches it — this guard fires
        only for a connector that has been idle for a year.
        """
        return now.timestamp() >= self.refresh_token_expiration

    def carrying_previous(self, *, spent_refresh_token: str, rotated_at: int) -> CloverTokenSet:
        """This record, stamped with the refresh token it just replaced.

        The store calls this between receiving a rotation and persisting it, so the record
        that lands always names its own recovery credential. A record persisted WITHOUT this
        stamp is one lost write away from an unrecoverable merchant.
        """
        return replace(self, previous_refresh_token=spent_refresh_token, previous_rotated_at=rotated_at)
