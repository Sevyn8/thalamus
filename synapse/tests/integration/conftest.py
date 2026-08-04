"""Shared vacuity guard for Synapse's live tests.

WHY THIS EXISTS. Several tests in this directory prove statements about ROWS. Run against a
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
