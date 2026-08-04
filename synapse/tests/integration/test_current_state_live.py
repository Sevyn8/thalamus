"""One live read of canonical, SKIPPED unless a DSN is supplied.

DELIBERATELY NOT RUNNABLE UNDER ithina_dis_user. That role holds full DML on
canonical; pointing a read-only analytics plane at it is the same mistake as pointing
mirror-sync at cm-database-url instead of dis_mirror_reader, which this project
rejected on exactly those grounds. The identity is `synapse_reader`: USAGE on
canonical, SELECT on exactly two tables, NOSUPERUSER NOBYPASSRLS — the
dis_mirror_reader pattern, mirrored resource for resource.

PROVISIONING THAT ROLE IS ITS OWN SLICE, and until it lands this skips by default — it
is here to be ready, not to be run today. Once it exists: supply SYNAPSE_READER_URL plus
SYNAPSE_TEST_TENANT_ID. Against staging also export DIS_EXPECTED_DATABASE=thalamus, or
dis-rls refuses the database before any query.

The env var is named SYNAPSE_READER_URL rather than POSTGRES_URL on purpose: reusing
the DIS variable name would make it trivially easy to point this at a writer's DSN by
accident, which is the exact outcome the paragraph above rules out.

DATA REQUIRED, and the previous version of this file was wrong about that. It said "an
empty result is a PASS", which is true of the READ but not of the property this test
exists for: every returned row is validated against StoreSkuCurrentPosition, and on
zero rows the loop body never runs, so the validation — the loud-failure guarantee that
is the whole reason the resolver selects all 45 columns — is never exercised. It now
refuses rather than reporting success having checked nothing. See the conftest.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Coroutine
from typing import Any
from uuid import UUID

import pytest

DSN = os.environ.get("SYNAPSE_READER_URL")
TENANT = os.environ.get("SYNAPSE_TEST_TENANT_ID")

pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        not DSN or not TENANT,
        reason=(
            "needs SYNAPSE_READER_URL (a synapse_reader DSN, NOT ithina_dis_user) and "
            "SYNAPSE_TEST_TENANT_ID; against staging also DIS_EXPECTED_DATABASE=thalamus"
        ),
    ),
]

# Structural alias for the conftest fixture's callable. Declared rather than imported: the
# suite runs under --import-mode=importlib with no __init__.py, so a sibling import of
# conftest is fragile. The fixture itself arrives by name, which is not.
RequireRows = Callable[..., Coroutine[Any, Any, int]]


async def test_resolves_current_state_against_staging(require_canonical_rows: RequireRows) -> None:
    """Read a real tenant's positions and validate every row against canonical.

    DATA REQUIRED. The read executing is not what this proves — the projection loop is, and
    it is where StoreSkuCurrentPosition.model_validate runs on every row. At zero rows the
    loop body never executes and this test reports success having validated nothing, which is
    exactly the state a canonical rename would sail through.

    With rows, it catches: a moved canonical shape (a dropped or ADDED column, since the
    model is extra='forbid'), an RLS policy that stopped scoping by tenant, and a
    synapse_reader whose grant is missing (which errors rather than returning empty).
    """
    from dis_rls import create_rls_engine, rls_session
    from synapse.core.capability import CapabilityScope
    from synapse.resolvers.current_state import resolve_current_state

    scope = CapabilityScope(tenant_id=UUID(str(TENANT)))
    engine = create_rls_engine(DSN)
    try:
        async with rls_session(engine, scope.tenant_id) as conn:
            await require_canonical_rows(
                conn,
                scope.tenant_id,
                table="current_position",
                what="it validates every returned row against the canonical model",
            )
        rows = await resolve_current_state(engine, scope, limit=25)
    finally:
        await engine.dispose()

    # Rows exist (guarded above), so a resolver returning none means the read and the count
    # disagree — a narrowing bug or an RLS policy that scopes differently per statement.
    assert rows, "the tenant has positions but the resolver returned none"

    # Every returned row is the projection, and every one was validated to get here.
    for row in rows:
        assert row.tenant_id == UUID(str(TENANT)), "RLS + the tenant predicate must agree"
        assert row.currency, "currency is NOT NULL in canonical"
