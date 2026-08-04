"""Shared vacuity guard for Synapse's live tests, and how to run them at all.

HOW TO RUN THESE AGAINST STAGING — the whole invocation, in one copy-pasteable place, because
it has four requirements and three of them fail in ways that do not name themselves.

    cd dis && \\
      DIS_EXPECTED_DATABASE=thalamus \\
      SYNAPSE_READER_URL='postgresql+psycopg://synapse_reader:<PW>@10.55.0.3:5432/thalamus?sslmode=require' \\
      SYNAPSE_TEST_TENANT_ID='<tenant-uuid>' \\
      uv run pytest -c pyproject.toml -p no:dis_testing ../synapse/tests/integration

Each part, and what its absence looks like:

- ``SYNAPSE_READER_URL`` — the synapse_reader DSN. NOT ithina_dis_user, which holds full DML on
  canonical and would make a read-only plane's tests prove nothing about its read-only-ness.
  The password is in Secret Manager as ``thalamus-synapse_reader-password``; the assembled DSN
  is ``synapse-reader-database-url``, created by hand (Terraform only reads those). Driver is
  ``postgresql+psycopg``, never asyncpg — asyncpg is not a workspace dependency and the wrong
  scheme fails as ``ModuleNotFoundError``, which reads as a missing package rather than a bad
  DSN.
- ``DIS_EXPECTED_DATABASE=thalamus`` — dis-rls refuses any database except its expected one,
  defaulting to the local ``ithina_dis_db``. Without this every test fails with
  ``RlsContextError`` before touching a row. Not a permission error, and not obviously a
  config one.
- ``-p no:dis_testing`` — ``dis-testing`` registers a ``pytest11`` entry point, so it
  auto-loads into any suite that has the package installed, which Synapse does via the shared
  uv workspace. Its session-scoped autouse ``_dis_identity_synced`` runs an identity-mirror
  sync that assumes the LOCAL stack. Against staging it must be off.
- NETWORK ACCESS. The instance is ``ipv4_enabled = false`` — private IP only,
  ``ssl_mode = ENCRYPTED_ONLY`` — so the DSN above (10.55.0.3) is only reachable from inside
  the VPC: the Cloud SQL Auth Proxy, or a VM / Cloud Shell in it. **Whatever access is opened
  to run this must be closed afterwards.** Opening a public-IP window out of band also drifts
  the instance from Terraform, where ``ipv4_enabled`` is false.

Locally, only the first is needed —
``postgresql+psycopg://synapse_reader:synapse_reader_password@localhost:5433/ithina_dis_db``
plus the tenant id. ``DIS_EXPECTED_DATABASE`` already defaults to the local database name, and
``dis_testing``'s sync is correct there.

WHY THIS FILE EXISTS. Several tests in this directory prove statements about ROWS. Run against a
canonical schema with no rows, every one of them reduces to ``0 == 0`` and reports success
having verified nothing. A skipped test is quiet and honest; a GREEN test that proved nothing
gets believed, cited in reviews, and is strictly worse than a red one.

So those tests take the ``require_canonical_rows`` fixture and RAISE — never skip — when the
table is empty. The posture is dis/tests/integration/test_rls_platform_session_guard.py,
which refuses to skip when its stack is absent.

THE DATA SITUATION, stated once here rather than in each test. ``make seed`` writes a single
``config.source_mappings`` row and explicitly nothing else: ``identity_mirror`` belongs to
mirror-sync, and NO fixture anywhere inserts sale events or current positions. Canonical rows
in a local devbox are RESIDUE from having run the streaming consumer's integration tests
against the same volume — arbitrary content, no guarantee of presence, nobody maintaining it.
Reading a green local run as proof of correction-collapse is reading residue.

A FIXTURE RATHER THAN AN IMPORTABLE HELPER, deliberately: the suite runs under
``--import-mode=importlib`` with no ``__init__.py``, so a sibling-module import is fragile in
a way a fixture is not. Shared rather than copied per file because two byte-identical guards
in one directory is how the duplicated Pub/Sub poll loop started, and that is already a
ledger item.
"""

from __future__ import annotations

from collections.abc import Callable, Coroutine
from typing import Any, Literal

import pytest
from sqlalchemy import TextClause, text
from sqlalchemy.ext.asyncio import AsyncConnection

# Keyed by the SHORT name a test asks for, so a test never spells a canonical table itself —
# these two are the only ones Synapse reads at all, and the only two its read-only role is
# granted when that role is provisioned.
_COUNTS: dict[str, TextClause] = {
    "sale_events": text(
        "SELECT COUNT(*) FROM canonical.store_sku_sale_events "
        "WHERE tenant_id = CAST(:tenant AS uuid)"
    ),
    "current_position": text(
        "SELECT COUNT(*) FROM canonical.store_sku_current_position "
        "WHERE tenant_id = CAST(:tenant AS uuid)"
    ),
}

Table = Literal["sale_events", "current_position"]
RequireRows = Callable[..., Coroutine[Any, Any, int]]


class CanonicalDataRequiredError(RuntimeError):
    """This test proves a statement about rows, and there are none.

    Raised, never skipped. See the module docstring for why that distinction is the whole
    point of this file.
    """


@pytest.fixture
def require_canonical_rows() -> RequireRows:
    """Count rows in scope; raise ``CanonicalDataRequiredError`` if there are none.

    Deliberately NOT a fixture that CREATES data. Synapse is read-only on canonical and must
    stay that way — the table-name containment test and the no-write-statement test both
    exist to keep it so, and a test helper that inserted rows would be the first crack. The
    only honest response to an empty table is to refuse.

    ``what`` names the claim the test cannot make without rows, so the failure says what is
    unproven rather than merely that something is missing.
    """

    async def _require(
        conn: AsyncConnection,
        tenant_id: object,
        *,
        table: Table,
        what: str,
    ) -> int:
        rows = int((await conn.execute(_COUNTS[table], {"tenant": str(tenant_id)})).scalar_one())
        if not rows:
            raise CanonicalDataRequiredError(
                f"no canonical rows in {table} for tenant {tenant_id} - this test cannot "
                f"prove anything without data ({what}). `make seed` does NOT write canonical; "
                "local rows are residue from streaming-consumer integration runs, not a "
                "fixture. Point SYNAPSE_READER_URL at staging, or run the consumer's "
                "integration suite first."
            )
        return rows

    return _require
