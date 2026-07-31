"""One live read of canonical, SKIPPED unless a DSN is supplied.

DELIBERATELY NOT RUNNABLE UNDER ithina_dis_user. That role holds full DML on
canonical; pointing a read-only analytics plane at it is the same mistake as pointing
mirror-sync at cm-database-url instead of dis_mirror_reader, which this project
rejected on exactly those grounds. The intended identity is a `synapse_reader`
(USAGE on canonical, SELECT on named tables, NOSUPERUSER NOBYPASSRLS — the
dis_mirror_reader pattern), and provisioning it is terraform, which is the first infra
item of the NEXT slice.

So this test skips by default and stays skipped until that role exists. It is here to
be ready, not to be run today. Supply SYNAPSE_READER_URL plus SYNAPSE_TEST_TENANT_ID
to run it.

The env var is named SYNAPSE_READER_URL rather than POSTGRES_URL on purpose: reusing
the DIS variable name would make it trivially easy to point this at a writer's DSN by
accident, which is the exact outcome the paragraph above rules out.
"""

from __future__ import annotations

import os
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
            "SYNAPSE_TEST_TENANT_ID; the read-only role is the next slice's first infra item"
        ),
    ),
]


async def test_resolves_current_state_against_staging() -> None:
    """Read a real tenant's positions and validate every row against canonical.

    An empty result is a PASS: a tenant with no ingested positions is a legitimate
    state, and this test is verifying that the read and the validation work — not that
    data exists. What it would catch is a canonical shape that has moved, since every
    row goes through StoreSkuCurrentPosition on the way out.
    """
    from dis_rls import create_rls_engine
    from synapse.core.capability import CapabilityScope
    from synapse.resolvers.current_state import resolve_current_state

    engine = create_rls_engine(DSN)
    try:
        rows = await resolve_current_state(engine, CapabilityScope(tenant_id=UUID(str(TENANT))), limit=25)
    finally:
        await engine.dispose()

    # Every returned row is the projection, and every one was validated to get here.
    for row in rows:
        assert row.tenant_id == UUID(str(TENANT)), "RLS + the tenant predicate must agree"
        assert row.currency, "currency is NOT NULL in canonical"
