"""``GET /api/v1/runs`` against the LIVE stack — audit-derived run state (Slice 51a, D117-D120).

Two concerns. HTTP shape/scope: the endpoint is VALID against the real schema and TENANT-SCOPED
live (the isolation test seeds two tenants via an admin/RLS-bypassing connection, reads back
through the scoped repo, then cleans up — D100). Audit-derived behaviour: seeded bronze + audit
rows prove the verdict/counts/completion/seen-before/names/file-name derive from the AUDIT trail
(not bronze.processing_status), each expected value read INDEPENDENTLY from its seeded source.

Loud-error posture (the Slice 4/7/8 lesson): a missing stack env var ERRORS, never skips.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import create_async_engine

from dis_rls import create_rls_engine
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.main import create_app
from dis_ui_server.pagination import Boundary
from dis_ui_server.repos.runs import list_runs

pytestmark = pytest.mark.integration

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees (live seed)
TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"  # zabka-group (live seed)

_VALID_STATUS = {"processing", "succeeded", "quarantined", "failed"}
_VALID_METHOD = {"csv_upload", "api", "csv_erp", "reverse_api"}

_MARK_A1 = "runs-live-marker-A1"
_MARK_A2 = "runs-live-marker-A2"
_MARK_B1 = "runs-live-marker-B1"
_ALL_MARKS = (_MARK_A1, _MARK_A2, _MARK_B1)

_INSERT = text(
    "INSERT INTO bronze.data_ingress_events "
    "(tenant_id, source_id, dis_channel, trace_id, gcs_uri, received_at, "
    "processing_status, source_payload_id) "
    "VALUES (:tenant, 'manual_csv_upload', 'csv_upload', uuidv7(), 'gs://test/x', "
    "now(), 'PROCESSED', :marker)"
)

# -- Slice 51a seeding: a bronze run (RETURNING id) + audit rows keyed to it ----------

_MARK51 = "runs51a-"  # prefix for the audit-derived tests' bronze markers (cleanup by prefix)

_SEED_BRONZE = text(
    "INSERT INTO bronze.data_ingress_events "
    "(tenant_id, store_id, source_id, dis_channel, trace_id, gcs_uri, row_count, "
    " template_id, original_filename, received_at, processing_status, source_payload_id) "
    "VALUES (:tenant, :store_id, :source_id, 'csv_upload', uuidv7(), 'gs://test/x', :row_count, "
    " :template_id, :original_filename, now(), :processing_status, :marker) "
    "RETURNING id"
)

_SEED_AUDIT = text(
    "INSERT INTO audit.events "
    "(event_timestamp, event_date, trace_id, tenant_id, data_ingress_event_id, service_name, "
    " stage, event_scope, outcome, row_count, rows_succeeded, mapping_version_id, event_data) "
    "VALUES (now(), (now() AT TIME ZONE 'UTC')::date, uuidv7(), :tenant, :bronze_id, "
    " 'streaming-consumer', :stage, 'INGRESS_EVENT', :outcome, :row_count, :rows_succeeded, "
    " :mv, CAST(:event_data AS jsonb))"
)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def live_client(stack_env: dict[str, str], monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    monkeypatch.setenv("POSTGRES_URL", stack_env["POSTGRES_URL"])
    with TestClient(create_app()) as client:
        yield client


def _assert_well_shaped(body: dict[str, object]) -> None:
    items = body["items"]
    assert isinstance(items, list)
    assert len(items) <= 100  # the bound
    # Slice 51b: the envelope carries next_cursor (opaque token or null), beside items.
    assert body["next_cursor"] is None or isinstance(body["next_cursor"], str)
    prev: str | None = None
    for row in items:
        assert isinstance(row, dict)
        assert isinstance(row["id"], str) and isinstance(row["trace_id"], str)
        assert isinstance(row["received_at"], str) and row["received_at"].endswith("Z")
        assert isinstance(row["source_id"], str)
        assert row["method"] in _VALID_METHOD
        assert row["status"] in _VALID_STATUS
        assert row["store_id"] is None or isinstance(row["store_id"], str)
        assert row["mapping_version"] is None or isinstance(row["mapping_version"], int)
        # audit-derived counts: three independent numbers, each int-or-null.
        for k in ("input_row_count", "accepted", "quarantined"):
            assert row[k] is None or isinstance(row[k], int)
        # id + name pairs: name may be null, never missing.
        for k in ("store_name", "source_name", "template_name", "file_name"):
            assert k in row and (row[k] is None or isinstance(row[k], str))
        assert isinstance(row["seen_before"], bool)
        completed = row["completed_at"]
        assert completed is None or (isinstance(completed, str) and completed.endswith("Z"))
        # PII / payload columns never present.
        for pii in ("auth_principal", "client_ip", "user_agent", "gcs_uri"):
            assert pii not in row
        assert "last_updated_at" not in row  # AC6: dropped in Slice 51b (D125)
        if prev is not None:
            assert row["received_at"] <= prev  # newest-first
        prev = row["received_at"]


def test_runs_valid_and_scoped_for_tenant_a(live_client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = live_client.get("/api/v1/runs", headers=_bearer(mint_token(tenant_id=TENANT_A)))
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_runs_valid_for_tenant_b(live_client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = live_client.get("/api/v1/runs", headers=_bearer(mint_token(tenant_id=TENANT_B)))
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_runs_platform_ops_sees_widened_set(live_client: TestClient, mint_token: Callable[..., str]) -> None:
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:ops", "dis:read"))
    resp = live_client.get("/api/v1/runs", headers=_bearer(token))
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_runs_requires_a_token(live_client: TestClient) -> None:
    assert live_client.get("/api/v1/runs").status_code == 401


async def test_runs_tenant_isolation_over_bronze(stack_env: dict[str, str]) -> None:
    """Prove tenant scoping live: seed A + B, read scoped, clean."""
    admin_engine = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])  # superuser: bypasses RLS
    rls_engine = create_rls_engine(stack_env["POSTGRES_URL"])  # NOBYPASSRLS: the real read path
    try:
        async with admin_engine.begin() as conn:
            await conn.execute(_INSERT, {"tenant": TENANT_A, "marker": _MARK_A1})
            await conn.execute(_INSERT, {"tenant": TENANT_A, "marker": _MARK_A2})
            await conn.execute(_INSERT, {"tenant": TENANT_B, "marker": _MARK_B1})

        def _markers(rows: Sequence[Row[Any]]) -> set[str]:
            return {r.source_payload_id for r in rows}

        scope_a = ReadScope(is_platform=False, tenant_id=UUID(TENANT_A))
        scope_b = ReadScope(is_platform=False, tenant_id=UUID(TENANT_B))
        a_rows = await list_runs(rls_engine, scope_a, limit=100)
        b_rows = await list_runs(rls_engine, scope_b, limit=100)
        p_rows = await list_runs(rls_engine, ReadScope(is_platform=True, tenant_id=None), limit=100)

        a_marks, b_marks, p_marks = _markers(a_rows), _markers(b_rows), _markers(p_rows)
        assert {_MARK_A1, _MARK_A2} <= a_marks and _MARK_B1 not in a_marks
        assert _MARK_B1 in b_marks and _MARK_A1 not in b_marks and _MARK_A2 not in b_marks
        assert {_MARK_A1, _MARK_A2, _MARK_B1} <= p_marks
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM bronze.data_ingress_events WHERE source_payload_id = ANY(:marks)"),
                {"marks": list(_ALL_MARKS)},
            )
        await admin_engine.dispose()
        await rls_engine.dispose()


# -- Slice 51a: audit-derived verdict / counts / seen-before / names / file-name ------


async def _seed_bronze(
    conn: Any,
    *,
    marker: str,
    row_count: int,
    processing_status: str = "RECEIVED",
    store_id: str | None = None,
    source_id: str = "manual_csv_upload",
    template_id: str | None = None,
    original_filename: str | None = None,
) -> UUID:
    result = await conn.execute(
        _SEED_BRONZE,
        {
            "tenant": TENANT_A,
            "store_id": store_id,
            "source_id": source_id,
            "row_count": row_count,
            "template_id": template_id,
            "original_filename": original_filename,
            "processing_status": processing_status,
            "marker": marker,
        },
    )
    return UUID(str(result.scalar_one()))


async def _seed_audit(
    conn: Any,
    *,
    bronze_id: UUID,
    stage: str,
    outcome: str,
    row_count: int | None = None,
    rows_succeeded: int | None = None,
    mv: int | None = None,
    event_data: dict[str, Any] | None = None,
) -> None:
    await conn.execute(
        _SEED_AUDIT,
        {
            "tenant": TENANT_A,
            "bronze_id": bronze_id,
            "stage": stage,
            "outcome": outcome,
            "row_count": row_count,
            "rows_succeeded": rows_succeeded,
            "mv": mv,
            "event_data": json.dumps(event_data) if event_data is not None else None,
        },
    )


async def test_run_state_derives_from_audit(stack_env: dict[str, str]) -> None:
    """AC1/AC2/AC4/AC5/AC7: verdict, counts, file-name, seen-before — all from the seeded audit
    trail and bronze columns, read INDEPENDENTLY (input from bronze.row_count, not from accepted).
    Includes the AC2 proof: a run whose bronze.processing_status is stale ('RECEIVED') but whose
    audit shows CANONICAL_WRITTEN/SUCCESS reads 'succeeded' — the verdict ignores bronze status.
    """
    admin_engine = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])
    rls_engine = create_rls_engine(stack_env["POSTGRES_URL"])
    m_ok = f"{_MARK51}succeeded"
    m_q = f"{_MARK51}quarantined"
    m_f = f"{_MARK51}failed"
    m_p = f"{_MARK51}processing"
    m_dup = f"{_MARK51}dup"
    seeded: list[UUID] = []
    try:
        async with admin_engine.begin() as conn:
            # succeeded (event path): stale bronze RECEIVED, audit CANONICAL_WRITTEN/SUCCESS N rows
            ok = await _seed_bronze(
                conn,
                marker=m_ok,
                row_count=100,
                processing_status="RECEIVED",
                original_filename="june-sales.csv",
            )
            await _seed_audit(
                conn,
                bronze_id=ok,
                stage="CANONICAL_WRITTEN",
                outcome="SUCCESS",
                row_count=100,
                rows_succeeded=100,
                mv=7,
                event_data={"written_to_table": "canonical.store_sku_sale_events"},
            )
            # quarantined: gate FAILURE + QUARANTINED/SUCCESS disposition (row_count = whole chunk)
            q = await _seed_bronze(conn, marker=m_q, row_count=40, processing_status="RECEIVED")
            await _seed_audit(
                conn,
                bronze_id=q,
                stage="PRE_MAPPING_VALIDATED",
                outcome="FAILURE",
                row_count=40,
                rows_succeeded=None,
                mv=7,
            )
            await _seed_audit(
                conn,
                bronze_id=q,
                stage="QUARANTINED",
                outcome="SUCCESS",
                row_count=40,
                rows_succeeded=None,
                mv=7,
            )
            # failed: a pure nack FAILURE, no QUARANTINED/CANONICAL_WRITTEN
            f = await _seed_bronze(conn, marker=m_f, row_count=25, processing_status="RECEIVED")
            await _seed_audit(
                conn,
                bronze_id=f,
                stage="MAPPING_EXECUTED",
                outcome="FAILURE",
                row_count=25,
                rows_succeeded=None,
                mv=7,
            )
            # processing: no terminal audit event at all
            await _seed_bronze(conn, marker=m_p, row_count=10, processing_status="PUBLISHED")
            # duplicate: seen-before from a recorded DUPLICATE_NOOP
            dup = await _seed_bronze(conn, marker=m_dup, row_count=5, processing_status="PUBLISHED")
            await _seed_audit(conn, bronze_id=dup, stage="RECEIVED", outcome="DUPLICATE_NOOP", row_count=5)
            seeded += [ok, q, f, dup]

        rows = await list_runs(rls_engine, ReadScope(is_platform=False, tenant_id=UUID(TENANT_A)), limit=100)
        by_marker = {r.source_payload_id: r for r in rows}

        from dis_ui_server.handlers.runs import _to_row  # map to the wire shape

        ok_w = _to_row(by_marker[m_ok])
        assert ok_w.status == "succeeded"  # AC2: derived from audit, ignores stale RECEIVED bronze
        assert ok_w.input_row_count == 100 and ok_w.accepted == 100 and ok_w.quarantined == 0
        assert ok_w.mapping_version == 7 and ok_w.completed_at is not None
        assert ok_w.file_name == "june-sales.csv" and ok_w.seen_before is False  # AC4/AC5

        q_w = _to_row(by_marker[m_q])
        assert q_w.status == "quarantined" and q_w.accepted == 0 and q_w.quarantined == 40  # AC7

        f_w = _to_row(by_marker[m_f])
        assert f_w.status == "failed" and f_w.accepted == 0 and f_w.quarantined is None

        p_w = _to_row(by_marker[m_p])
        assert p_w.status == "processing" and p_w.accepted is None and p_w.quarantined is None

        assert _to_row(by_marker[m_dup]).seen_before is True  # AC5
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM audit.events WHERE data_ingress_event_id = ANY(:ids)"),
                {"ids": seeded},
            )
            await conn.execute(
                text("DELETE FROM bronze.data_ingress_events WHERE source_payload_id LIKE :p"),
                {"p": f"{_MARK51}%"},
            )
        await admin_engine.dispose()
        await rls_engine.dispose()


async def test_store_name_resolves_and_status_filter_on_verdict(stack_env: dict[str, str]) -> None:
    """AC3 (store name resolves via identity_mirror; absent tolerated) + AC8 (status filter runs
    against the derived verdict)."""
    admin_engine = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])
    rls_engine = create_rls_engine(stack_env["POSTGRES_URL"])
    m_named = f"{_MARK51}named"
    m_nostore = f"{_MARK51}nostore"
    seeded: list[UUID] = []
    try:
        async with admin_engine.begin() as conn:
            store = (
                await conn.execute(
                    text("SELECT store_id, name FROM identity_mirror.stores WHERE tenant_id = :t LIMIT 1"),
                    {"t": TENANT_A},
                )
            ).one()
            named = await _seed_bronze(conn, marker=m_named, row_count=3, store_id=str(store.store_id))
            await _seed_audit(
                conn,
                bronze_id=named,
                stage="CANONICAL_WRITTEN",
                outcome="SUCCESS",
                row_count=3,
                rows_succeeded=3,
                mv=7,
                event_data={"written_to_table": "canonical.store_sku_sale_events"},
            )
            nostore = await _seed_bronze(conn, marker=m_nostore, row_count=3, store_id=None)
            await _seed_audit(
                conn, bronze_id=nostore, stage="PRE_MAPPING_VALIDATED", outcome="FAILURE", row_count=3, mv=7
            )
            await _seed_audit(
                conn, bronze_id=nostore, stage="QUARANTINED", outcome="SUCCESS", row_count=3, mv=7
            )
            seeded += [named, nostore]

        scope = ReadScope(is_platform=False, tenant_id=UUID(TENANT_A))
        # AC3: the named run resolves store_name; the store-less run is null, not an error.
        all_rows = {r.source_payload_id: r for r in await list_runs(rls_engine, scope, limit=100)}
        assert all_rows[m_named].store_name == store.name
        assert all_rows[m_nostore].store_name is None

        # AC8: status filter applies to the DERIVED verdict.
        succ_rows = await list_runs(rls_engine, scope, limit=100, status="succeeded")
        succ = {r.source_payload_id for r in succ_rows}
        assert m_named in succ and m_nostore not in succ
        quar_rows = await list_runs(rls_engine, scope, limit=100, status="quarantined")
        quar = {r.source_payload_id for r in quar_rows}
        assert m_nostore in quar and m_named not in quar
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM audit.events WHERE data_ingress_event_id = ANY(:ids)"), {"ids": seeded}
            )
            await conn.execute(
                text("DELETE FROM bronze.data_ingress_events WHERE source_payload_id LIKE :p"),
                {"p": f"{_MARK51}%"},
            )
        await admin_engine.dispose()
        await rls_engine.dispose()


# -- Slice 51b: keyset pagination — walk, stability under concurrent insert, filter compose ----

_MARK51B = "runs51b-"


async def _cleanup_51b(admin_engine: Any, seeded: list[UUID]) -> None:
    async with admin_engine.begin() as conn:
        await conn.execute(
            text("DELETE FROM audit.events WHERE data_ingress_event_id = ANY(:ids)"), {"ids": seeded}
        )
        await conn.execute(
            text("DELETE FROM bronze.data_ingress_events WHERE source_payload_id LIKE :p"),
            {"p": f"{_MARK51B}%"},
        )


async def test_keyset_walk_covers_all_pages_without_dupes(stack_env: dict[str, str]) -> None:
    """AC1: cursor-by-boundary paging walks the whole history; each row appears exactly once and
    the walk terminates (the over-fetch of one row signals the last page). Assertions are scoped
    to this test's markers, so residue in the tenant cannot break them."""
    admin_engine = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])
    rls_engine = create_rls_engine(stack_env["POSTGRES_URL"])
    seeded: list[UUID] = []
    try:
        async with admin_engine.begin() as conn:
            for n in range(5):
                seeded.append(await _seed_bronze(conn, marker=f"{_MARK51B}walk-{n}", row_count=1))
        scope = ReadScope(is_platform=False, tenant_id=UUID(TENANT_A))
        page_size, after, seen, pages = 2, None, [], 0
        while True:
            rows = await list_runs(rls_engine, scope, limit=page_size, after=after)
            page = rows[:page_size]
            seen += [r.source_payload_id for r in page]
            pages += 1
            assert pages < 200, "keyset walk did not terminate"
            if len(rows) > page_size:
                last = page[-1]
                after = Boundary(received_at=last.received_at, id=last.id)
            else:
                break
        mine = [m for m in seen if m and m.startswith(f"{_MARK51B}walk-")]
        assert sorted(mine) == [f"{_MARK51B}walk-{n}" for n in range(5)]  # all 5 seen
        assert len(mine) == len(set(mine))  # exactly once each — no repeat across pages
    finally:
        await _cleanup_51b(admin_engine, seeded)
        await admin_engine.dispose()
        await rls_engine.dispose()


async def test_keyset_stable_under_concurrent_insert(stack_env: dict[str, str]) -> None:
    """AC2 (the explicit proof): compute a page-1 boundary, INSERT a new top row, then fetch the
    next (older) page by that boundary — the new row must be ABSENT (it sorts above the
    boundary), the page-1 rows must NOT repeat, and the older row must be PRESENT (not skipped).
    All three stable rows share one received_at (seed txn timestamp), so this also exercises the
    id tie-break within a same-second cluster."""
    admin_engine = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])
    rls_engine = create_rls_engine(stack_env["POSTGRES_URL"])
    seeded: list[UUID] = []
    try:
        async with admin_engine.begin() as conn:  # r1<r2<r3 by id, all at received_at T1
            for n in (1, 2, 3):
                seeded.append(await _seed_bronze(conn, marker=f"{_MARK51B}stable-{n}", row_count=1))
        scope = ReadScope(is_platform=False, tenant_id=UUID(TENANT_A))
        # Read my three rows in the REAL (received_at DESC, id DESC) order — do not assume the
        # UUIDv7 ids follow seed order (same-millisecond ids are not insertion-ordered).
        ordered = [
            r
            for r in await list_runs(rls_engine, scope, limit=100)
            if (r.source_payload_id or "").startswith(f"{_MARK51B}stable-")
        ]
        assert len(ordered) == 3
        top, mid, bottom = ordered[0], ordered[1], ordered[2]  # page-1 = [top, mid]; boundary = mid
        after = Boundary(received_at=mid.received_at, id=mid.id)
        async with admin_engine.begin() as conn:  # a NEW run arrives at the top (later received_at)
            seeded.append(await _seed_bronze(conn, marker=f"{_MARK51B}stable-newtop", row_count=1))
        page2 = {r.source_payload_id for r in await list_runs(rls_engine, scope, limit=100, after=after)}
        assert bottom.source_payload_id in page2  # the row after the boundary — present, not skipped
        assert mid.source_payload_id not in page2  # boundary itself excluded
        assert top.source_payload_id not in page2  # page-1 row not repeated
        assert f"{_MARK51B}stable-newtop" not in page2  # concurrent top insert not served on an older page
    finally:
        await _cleanup_51b(admin_engine, seeded)
        await admin_engine.dispose()
        await rls_engine.dispose()


async def test_keyset_composes_with_status_filter(stack_env: dict[str, str]) -> None:
    """AC5 (composition): with a status filter active, cursor paging returns ONLY matching rows
    across pages and terminates. Seeds 3 succeeded + 2 quarantined; pages status='succeeded'."""
    admin_engine = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])
    rls_engine = create_rls_engine(stack_env["POSTGRES_URL"])
    seeded: list[UUID] = []
    try:
        async with admin_engine.begin() as conn:
            for n in range(3):  # succeeded
                bid = await _seed_bronze(conn, marker=f"{_MARK51B}ok-{n}", row_count=1)
                await _seed_audit(
                    conn,
                    bronze_id=bid,
                    stage="CANONICAL_WRITTEN",
                    outcome="SUCCESS",
                    row_count=1,
                    rows_succeeded=1,
                    mv=7,
                    event_data={"written_to_table": "canonical.store_sku_sale_events"},
                )
                seeded.append(bid)
            for n in range(2):  # quarantined
                bid = await _seed_bronze(conn, marker=f"{_MARK51B}quar-{n}", row_count=1)
                await _seed_audit(
                    conn, bronze_id=bid, stage="PRE_MAPPING_VALIDATED", outcome="FAILURE", row_count=1, mv=7
                )
                await _seed_audit(
                    conn, bronze_id=bid, stage="QUARANTINED", outcome="SUCCESS", row_count=1, mv=7
                )
                seeded.append(bid)
        scope = ReadScope(is_platform=False, tenant_id=UUID(TENANT_A))
        page_size, after, seen, pages = 2, None, [], 0
        while True:
            rows = await list_runs(rls_engine, scope, limit=page_size, status="succeeded", after=after)
            page = rows[:page_size]
            seen += [r.source_payload_id for r in page if (r.source_payload_id or "").startswith(_MARK51B)]
            pages += 1
            assert pages < 200, "filtered keyset walk did not terminate"
            if len(rows) > page_size:
                last = page[-1]
                after = Boundary(received_at=last.received_at, id=last.id)
            else:
                break
        assert not any(m.startswith(f"{_MARK51B}quar-") for m in seen)  # filter holds across pages
        assert {m for m in seen if m.startswith(f"{_MARK51B}ok-")} == {f"{_MARK51B}ok-{n}" for n in range(3)}
    finally:
        await _cleanup_51b(admin_engine, seeded)
        await admin_engine.dispose()
        await rls_engine.dispose()
