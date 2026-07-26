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

_SQUARE_API_BASE_URL = "SQUARE_API_BASE_URL"
_SQUARE_API_VERSION = "SQUARE_API_VERSION"

SANDBOX_BASE_URL = "https://connect.squareupsandbox.com"

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
