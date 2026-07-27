"""Environment-resolved Clover configuration (WorkerConfig.from_env pattern).

- ``CLOVER_API_BASE_URL`` - the Clover API base. Defaults to the NA SANDBOX host; a legit
  optional with a default (v1 targets sandbox), not a rule-4 silent fallback for a
  required value. Clover hosts are per-REGION as well as per-environment, so a
  production deploy sets this explicitly.

THERE IS NO API VERSION HEADER TO PIN. The Square lane pins ``Square-Version`` because
Square dates its API and applies the pinned version per request. Clover has NO equivalent:
probing the live sandbox returned only ``x-clover-request-id`` and
``x-clover-allowed-filter-fields`` - no version header on any response. Clover versions in
the URL PATH instead, hence :data:`API_PATH_VERSION`. This is written down so nobody goes
hunting for a header that does not exist.

The per-tenant access token and merchant id are NOT env config: they come from
``thalamus_clover_oauth.CloverTokenStore.get_session``, resolved per trigger tenant.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

# The NA sandbox host. Production is per-region (e.g. https://api.clover.com for NA).
SANDBOX_BASE_URL = "https://sandbox.dev.clover.com"

# Clover's API version lives in the path, not a header (see the module docstring). Every
# REST call is /{API_PATH_VERSION}/merchants/{merchant_id}/...
API_PATH_VERSION = "v3"

# Clover rejects limit > 1000 with HTTP 400 {"message":"limit cannot be greater than 1000"}
# (confirmed against the live sandbox 2026-07-27). Page at the cap: fewer round trips, and
# the collection endpoints are cheap.
PAGE_LIMIT_MAX = 1000

SERVICE_NAME = "thalamus-clover"


@dataclass(frozen=True)
class CloverConfig:
    """Resolved Clover API profile."""

    base_url: str

    @classmethod
    def from_env(cls) -> CloverConfig:
        return cls(base_url=os.environ.get("CLOVER_API_BASE_URL", SANDBOX_BASE_URL))
