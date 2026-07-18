"""Connector-health WRITE against the LIVE stack (D116) — the worker-write isolation proof.

This is the load-bearing test for a WORKER writing a tenant-scoped shared-DB table: the emit
rides ``rls_session`` under the event's tenant, so the two-GUC WITH CHECK pins every write to that
tenant (a worker cannot stamp health for another tenant), and a row written under tenant A is
invisible under a tenant-B session. Also proves the ON CONFLICT merge (a later success does not
clobber the prior error record, and vice versa). Errors, never skips: see ``conftest``.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING, Any

import pytest
from sqlalchemy import text
from sqlalchemy.engine import Engine

from csv_ingest_worker.connector_health import upsert_health_error, upsert_health_seen
from dis_rls import rls_session
from dis_testing.fixtures import TENANTS

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncEngine

pytestmark = pytest.mark.integration

TENANT_A = TENANTS[0].uuid  # buc-ees
TENANT_B = TENANTS[1].uuid  # zabka-group

# Unique source ids for this suite (exact-match cleanup; telemetry.connector_health is standalone
# — no config.sources FK — so these need no source registry row).
_SRC_SEEN = "cht_live_seen"
_SRC_MERGE = "cht_live_merge"
_SRC_XCHECK = "cht_live_xcheck"
_ALL_SRCS = [_SRC_SEEN, _SRC_MERGE, _SRC_XCHECK]


@pytest.fixture
def cleanup_health(dis_admin: Engine) -> Iterator[None]:
    """Remove this suite's connector_health rows (both tenants) on teardown (D100)."""
    yield
    with dis_admin.begin() as conn:
        conn.execute(
            text("DELETE FROM telemetry.connector_health WHERE source_id = ANY(:ids)"),
            {"ids": _ALL_SRCS},
        )


def _admin_row(dis_admin: Engine, source_id: str) -> Any:
    with dis_admin.connect() as conn:
        return conn.execute(
            text(
                "SELECT tenant_id, source_id, last_seen_at, last_error_at, last_error_detail, status "
                "FROM telemetry.connector_health WHERE source_id = :sid"
            ),
            {"sid": source_id},
        ).one_or_none()


async def test_seen_write_is_pinned_and_isolated(
    engine: AsyncEngine, dis_admin: Engine, cleanup_health: None
) -> None:
    # Emit under tenant A's session — WITH CHECK pins it to A.
    async with rls_session(engine, TENANT_A) as conn:
        await upsert_health_seen(conn, tenant_id=TENANT_A, source_id=_SRC_SEEN)

    row = _admin_row(dis_admin, _SRC_SEEN)
    assert row is not None
    assert row.tenant_id == TENANT_A
    assert row.status == "healthy"
    assert row.last_seen_at is not None

    # Read isolation: the row is invisible under a tenant-B session (RLS USING).
    async with rls_session(engine, TENANT_B) as conn:
        seen_by_b = (
            await conn.execute(
                text("SELECT count(*) FROM telemetry.connector_health WHERE source_id = :sid"),
                {"sid": _SRC_SEEN},
            )
        ).scalar_one()
    assert seen_by_b == 0


async def test_with_check_forbids_writing_another_tenant(
    engine: AsyncEngine, dis_admin: Engine, cleanup_health: None
) -> None:
    # Under tenant A's session, try to stamp a row FOR tenant B — the WITH CHECK
    # (tenant_id = app.tenant_id) must refuse it (the structural backstop).
    with pytest.raises(Exception) as exc_info:  # noqa: PT011 — RLS surfaces as a DBAPI error
        async with rls_session(engine, TENANT_A) as conn:
            await upsert_health_error(
                conn, tenant_id=TENANT_B, source_id=_SRC_XCHECK, detail="cross_tenant_attempt"
            )
    msg = str(exc_info.value).lower()
    assert "row-level security" in msg or "policy" in msg
    # And nothing landed for that source.
    assert _admin_row(dis_admin, _SRC_XCHECK) is None


async def test_on_conflict_merge_keeps_both_signals(
    engine: AsyncEngine, dis_admin: Engine, cleanup_health: None
) -> None:
    # An error stamp then a success stamp on the same (tenant, source): the merge keeps the
    # error record AND records the success — neither ON CONFLICT arm clobbers the other's column.
    async with rls_session(engine, TENANT_A) as conn:
        await upsert_health_error(conn, tenant_id=TENANT_A, source_id=_SRC_MERGE, detail="not_csv")
    async with rls_session(engine, TENANT_A) as conn:
        await upsert_health_seen(conn, tenant_id=TENANT_A, source_id=_SRC_MERGE)

    row = _admin_row(dis_admin, _SRC_MERGE)
    assert row is not None
    assert row.last_error_at is not None  # kept from the error stamp
    assert row.last_error_detail == "not_csv"
    assert row.last_seen_at is not None  # added by the success stamp
    assert row.status == "healthy"  # last write wins the coarse status
