"""Chunk 9 — tenant_name via the LOCAL identity_mirror.tenants LEFT JOIN, live-verified.

Proves against the running DB the two load-bearing properties the join must have:

1. NO ROW LOSS / NO MULTIPLICATION — the LEFT JOIN on the tenant PK (``tenant_id``) neither drops a
   data row (LEFT, so an unmirrored/NULL tenant still returns the row) nor multiplies it (PK ⇒ ≤1
   match). Asserted directly per fleet table: ``count(T) == count(T LEFT JOIN tenants)``.
2. A REAL NAME comes through — a mirrored tenant's row carries ``tenant_name`` = the actual
   identity_mirror.tenants.name (NOT the UUID); a system (NULL-tenant) audit row carries NULL.

Seeds a couple of rows for two mirrored tenants (buc-ees / zabka-group) + one NULL-tenant audit row,
asserts, then removes them (D100). Loud-error posture: a missing stack env ERRORS, never skips.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import UUID

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.ext.asyncio.engine import AsyncEngine

from dis_rls import create_rls_engine
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.repos.audit import list_events
from dis_ui_server.repos.dashboard import fetch_dashboard_metrics
from dis_ui_server.repos.runs import list_runs

pytestmark = pytest.mark.integration

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees (live seed, mirrored)
TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"  # zabka-group (live seed, mirrored)

# The five fleet tables the join is added to; each has a tenant_id column.
_FLEET_TABLES = (
    "bronze.data_ingress_events",
    "audit.events",
    "quarantine.quarantined_rows",
    "quarantine.quarantined_chunks",
    "config.sources",
)

_MARK = "chunk9live"  # bronze source_payload_id marker (cleanup by prefix)

_SEED_BRONZE = text(
    "INSERT INTO bronze.data_ingress_events "
    "(tenant_id, source_id, dis_channel, trace_id, gcs_uri, received_at, "
    " processing_status, source_payload_id) "
    "VALUES (:tenant, 'manual_csv_upload', 'csv_upload', uuidv7(), 'gs://test/x', "
    " now(), 'PROCESSED', :marker)"
)

_SEED_AUDIT = text(
    "INSERT INTO audit.events "
    "(event_timestamp, event_date, trace_id, tenant_id, service_name, stage, event_scope, "
    " outcome, row_count, rows_succeeded) "
    "VALUES (now(), (now() AT TIME ZONE 'UTC')::date, uuidv7(), :tenant, 'streaming-consumer', "
    " :stage, 'INGRESS_EVENT', :outcome, :row_count, :rows_succeeded) "
    "RETURNING id"
)

_PLATFORM = ReadScope(is_platform=True, tenant_id=None)


@pytest_asyncio.fixture
async def seeded(stack_env: dict[str, str]) -> AsyncIterator[dict[str, str]]:
    """Seed 2 bronze rows (A, B) + a RECEIVED/SUCCESS audit event for A (feeds by_tenant) + a
    NULL-tenant audit row, and yield the real mirrored names. Remove everything on teardown."""
    admin: AsyncEngine = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])
    audit_ids: list[UUID] = []
    async with admin.begin() as conn:
        await conn.execute(_SEED_BRONZE, {"tenant": TENANT_A, "marker": f"{_MARK}-a"})
        await conn.execute(_SEED_BRONZE, {"tenant": TENANT_B, "marker": f"{_MARK}-b"})
        # A RECEIVED/SUCCESS event for A → the dashboard by_tenant breakdown gets an A entry.
        audit_ids.append(
            (
                await conn.execute(
                    _SEED_AUDIT,
                    {"tenant": TENANT_A, "stage": "RECEIVED", "outcome": "SUCCESS",
                     "row_count": 100, "rows_succeeded": 100},
                )
            ).scalar_one()
        )
        # A NULL-tenant (system) audit row — outcome FAILURE so it never enters the ingest aggregate,
        # but it DOES appear in the audit list, exercising LEFT-JOIN-null (tenant_id NULL → no match).
        audit_ids.append(
            (
                await conn.execute(
                    _SEED_AUDIT,
                    {"tenant": None, "stage": "RECEIVED", "outcome": "FAILURE",
                     "row_count": None, "rows_succeeded": None},
                )
            ).scalar_one()
        )
        names = {
            str(r.tenant_id): r.name
            for r in (
                await conn.execute(
                    text("SELECT tenant_id, name FROM identity_mirror.tenants WHERE tenant_id = ANY(:ids)"),
                    {"ids": [TENANT_A, TENANT_B]},
                )
            ).all()
        }
    try:
        yield names
    finally:
        async with admin.begin() as conn:
            await conn.execute(
                text("DELETE FROM bronze.data_ingress_events WHERE source_payload_id LIKE :m"),
                {"m": f"{_MARK}%"},
            )
            await conn.execute(text("DELETE FROM audit.events WHERE id = ANY(:ids)"), {"ids": audit_ids})
        await admin.dispose()


async def test_tenant_join_neither_drops_nor_multiplies_rows(
    seeded: dict[str, str], stack_env: dict[str, str]
) -> None:
    """Row-count regression guard: for each fleet table, the LEFT JOIN to identity_mirror.tenants
    on the tenant PK leaves the row count IDENTICAL (LEFT ⇒ no drop; PK ⇒ ≤1 match ⇒ no multiply).
    bronze + audit are non-empty here (seeded), so this is a real ≤1-match proof, not 0 == 0."""
    admin = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])
    try:
        async with admin.connect() as conn:
            for table in _FLEET_TABLES:
                base = (await conn.execute(text(f"SELECT count(*) FROM {table}"))).scalar_one()
                joined = (
                    await conn.execute(
                        text(
                            f"SELECT count(*) FROM {table} d "
                            "LEFT JOIN identity_mirror.tenants t ON t.tenant_id = d.tenant_id"
                        )
                    )
                ).scalar_one()
                assert base == joined, f"{table}: tenant join changed the row count ({base} -> {joined})"
    finally:
        await admin.dispose()


async def test_runs_carry_real_tenant_name_for_mirrored_tenants(
    seeded: dict[str, str], stack_env: dict[str, str]
) -> None:
    """PLATFORM see-all: the seeded runs carry tenant_name = the real name, not the UUID."""
    rls = create_rls_engine(stack_env["POSTGRES_URL"])
    try:
        rows = await list_runs(rls, _PLATFORM, limit=500)
        seeded_runs = {
            str(r.tenant_id): r.tenant_name
            for r in rows
            if r.source_payload_id and r.source_payload_id.startswith(_MARK)
        }
        assert seeded_runs[TENANT_A] == seeded[TENANT_A]
        assert seeded_runs[TENANT_B] == seeded[TENANT_B]
        # A real name, never the raw UUID.
        assert seeded_runs[TENANT_A] != TENANT_A
    finally:
        await rls.dispose()


async def test_audit_real_name_and_null_tenant_is_null_name(
    seeded: dict[str, str], stack_env: dict[str, str]
) -> None:
    """A mirrored tenant's audit row carries the real name; the NULL-tenant system row carries a
    NULL name and is STILL returned (LEFT-JOIN-null, the honest system case)."""
    rls = create_rls_engine(stack_env["POSTGRES_URL"])
    try:
        events = await list_events(rls, _PLATFORM, limit=500)
        by_tenant = {
            (str(e.tenant_id) if e.tenant_id is not None else None): e.tenant_name for e in events
        }
        assert by_tenant[TENANT_A] == seeded[TENANT_A]  # real name
        # The NULL-tenant system row is present with a NULL name (never dropped, never fabricated).
        assert None in by_tenant
        assert by_tenant[None] is None
    finally:
        await rls.dispose()


async def test_dashboard_by_tenant_carries_real_tenant_name(
    seeded: dict[str, str], stack_env: dict[str, str]
) -> None:
    """The PLATFORM by_tenant breakdown carries tenant_name for the tenant it aggregated."""
    rls = create_rls_engine(stack_env["POSTGRES_URL"])
    try:
        data = await fetch_dashboard_metrics(rls, _PLATFORM)
        names = {t.tenant_id: t.tenant_name for t in data.by_tenant}
        assert names.get(TENANT_A) == seeded[TENANT_A]  # the seeded RECEIVED event → A entry, named
    finally:
        await rls.dispose()
