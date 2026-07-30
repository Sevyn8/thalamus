"""Environment-resolved connection profile for the Mirror Sync run.

Two env-resolved DSNs, **no hard-coded instance** (slice constraint / read contract §10):

- ``CM_DB_URL`` — the Customer Master read connection. Locally two separate Postgres
  instances (CM on 5432, DIS on 5433). In the CONSOLIDATED cloud deploy there is ONE
  instance (``thalamus-pg``) and ONE database (``thalamus``): CM and DIS are SCHEMAS in
  it (``core`` / ``identity_mirror``), and the separation is by ROLE. This connection
  is ``dis_mirror_reader`` — USAGE on ``core`` plus SELECT on exactly ``core.tenants``
  and ``core.stores``, nothing else. NOT ``user_admin_backend``, which owns ``core``
  and holds full DML.
- ``POSTGRES_URL`` — the DIS write connection (``ithina_dis_user``). Reused by
  ``dis-rls`` ``create_rls_engine``, whose ``current_database()`` guard is
  parameterised by ``DIS_EXPECTED_DATABASE`` (default ``ithina_dis_db``).

No silent default for a required value (code-quality rule 4): a missing ``CM_DB_URL`` or
``POSTGRES_URL`` raises. ``CM_DB_NAME`` is an assertion target, not a secret.

**TWO STALE DEFAULTS, both pre-consolidation.** ``DEFAULT_CM_DB_NAME``
(``ithina_platform_db``) and ``dis-rls``'s ``ithina_dis_db`` name databases that no
longer exist in the cloud deploy. Inheriting either fails loudly but confusingly — the
error names a database nobody has heard of. The Cloud Run job therefore sets
``CM_DB_NAME=thalamus`` and ``DIS_EXPECTED_DATABASE=thalamus`` EXPLICITLY
(``infra/modules/cloud-run-job-mirror-sync-consumer``). The defaults are left as-is for
the local two-instance topology, which still matches them.

**``DIS_DB_NAME`` BELOW IS AN INERT GUARD, recorded rather than fixed.** It exists so
``reader.py``'s ``assert_cm_target`` can refuse a CM read that landed on the DIS
database — "never read identity from the write target". Post-consolidation the CM read
target and the DIS write target ARE THE SAME DATABASE, so the comparison is against a
literal (``ithina_dis_db``) that no longer exists and the check can never fire. It is
harmless — the reads are schema-qualified ``core.*`` and the writes
``identity_mirror.*``, so no mix-up is actually possible — but the protection is
structurally inexpressible at database granularity now. Re-expressing it schema-wise is
a design question, not a rename; it is on the ledger. The second half of that guard
(``database != expected_cm_db``) still works and is what catches a wrong ``CM_DB_NAME``.
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from dis_core.errors import MirrorSyncError

_CM_DB_URL = "CM_DB_URL"
_POSTGRES_URL = "POSTGRES_URL"
_CM_DB_NAME = "CM_DB_NAME"

# The Customer Master database name (local and the cloud read replica share it).
DEFAULT_CM_DB_NAME = "ithina_platform_db"
# The DIS database — the only sanctioned write target (dis-rls hard-asserts it too).
DIS_DB_NAME = "ithina_dis_db"


@dataclass(frozen=True)
class MirrorSyncConfig:
    """Resolved connection profile for one Mirror Sync run."""

    cm_db_url: str
    dis_db_url: str
    cm_db_name: str = DEFAULT_CM_DB_NAME
    dis_db_name: str = DIS_DB_NAME

    @classmethod
    def from_env(cls) -> MirrorSyncConfig:
        """Resolve the profile from the environment, raising on a missing required value."""
        cm_db_url = os.environ.get(_CM_DB_URL)
        if not cm_db_url:
            raise MirrorSyncError(
                f"{_CM_DB_URL} is not set; cannot reach Customer Master for the DB-pull read"
            )
        dis_db_url = os.environ.get(_POSTGRES_URL)
        if not dis_db_url:
            raise MirrorSyncError(
                f"{_POSTGRES_URL} is not set; cannot reach the DIS database for the mirror write"
            )
        return cls(
            cm_db_url=cm_db_url,
            dis_db_url=dis_db_url,
            cm_db_name=os.environ.get(_CM_DB_NAME, DEFAULT_CM_DB_NAME),
        )
