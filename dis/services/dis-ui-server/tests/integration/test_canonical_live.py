"""``GET /api/v1/canonical/store-sku-positions`` against the LIVE stack (canonical read).

Proves the canonical read is VALID against the real ``store_sku_current_position`` schema and is
TENANT-SCOPED live. The HTTP tests assert shape / types / newest-first / the bound
(empty-tolerant). The isolation test SEEDS rows for two tenants via an admin (RLS-bypassing)
connection — using an EXISTING store + mapping_version per tenant so the FKs hold regardless of
seed state — then reads them back through the repo's scoped path (``read_session`` + the
defense-in-depth predicate) and asserts a TENANT sees only its own positions, the store filter
narrows, and PLATFORM see-all spans both. Seeded rows are removed afterwards (D100 clean-state).
tenant_id is not on the wire, so isolation is observed via a per-tenant ``sku_id`` marker.

Loud-error posture (the Slice 4/7/8 lesson): a missing stack env var ERRORS, never skips.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator, Sequence
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, Row, create_engine, text
from sqlalchemy.ext.asyncio import create_async_engine

from dis_rls import create_rls_engine
from dis_ui_server.auth.scope import ReadScope
from dis_ui_server.main import create_app
from dis_ui_server.repos.canonical import list_positions

pytestmark = pytest.mark.integration

TENANT_A = "019e5e3c-b5d3-705f-9002-2451c4ca2626"  # buc-ees (live seed)
TENANT_B = "019e5e3c-b5d6-7eed-93f9-3778a7a7a160"  # zabka-group (live seed)

_MARK_A1 = "CANON-SMOKE-A1"
_MARK_A2 = "CANON-SMOKE-A2"
_MARK_B1 = "CANON-SMOKE-B1"
_ALL_MARKS = (_MARK_A1, _MARK_A2, _MARK_B1)

_INSERT = text(
    "INSERT INTO canonical.store_sku_current_position "
    "(tenant_id, store_id, sku_id, product_name, current_retail_price, tax_treatment, "
    "currency, stock_qty, mapping_version_id, trace_id, dis_channel) "
    "VALUES (:tenant, :store, :sku, 'Smoke Product', 1299.0000, 'INCLUSIVE', "
    "'INR', 42.000, :mv, uuidv7(), 'csv_upload')"
)

# A richer seed (Slice 52a): sets extra NUMERICs and a populated jsonb staleness map so the
# full-column-set / store_name / size test reads a realistic row (not an all-null one). expiry_date
# is left null (the ck_sscp_expiry_triple_pairing constraint needs the date/source/confidence triple
# all-set-or-all-null; date rendering is covered at the unit layer instead).
_INSERT_RICH = text(
    "INSERT INTO canonical.store_sku_current_position "
    "(tenant_id, store_id, sku_id, product_name, current_retail_price, tax_treatment, "
    "currency, stock_qty, mapping_version_id, trace_id, dis_channel, "
    "unit_cost, sku_size, attribute_staleness_map) "
    "VALUES (:tenant, :store, :sku, 'Smoke Product', 1299.0000, 'INCLUSIVE', "
    "'INR', 42.000, :mv, uuidv7(), 'csv_upload', "
    "812.5000, 250.000, CAST(:asm AS jsonb))"
)

_SIZE_PREFIX = "CANON-52A-"  # markers for the full-set/size seed (cleaned in teardown)


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
    assert len(items) <= 50  # the bound
    prev: str | None = None
    for row in items:
        assert isinstance(row, dict)
        assert isinstance(row["id"], str) and isinstance(row["sku_id"], str)
        assert isinstance(row["product_name"], str) and isinstance(row["store_id"], str)
        assert isinstance(row["current_retail_price"], str)  # money-safe string
        assert row["stock_qty"] is None or isinstance(row["stock_qty"], str)
        assert isinstance(row["currency"], str)
        assert isinstance(row["mapping_version"], int)
        assert isinstance(row["last_updated_at"], str) and row["last_updated_at"].endswith("Z")
        assert row["last_source_event_at"] is None or isinstance(row["last_source_event_at"], str)
        assert "store_name" in row  # Slice 52a additive key
        assert row["store_name"] is None or isinstance(row["store_name"], str)
        for absent in ("tenant_id", "auth_principal", "ingest_metadata", "mapping_version_id"):
            assert absent not in row
        if prev is not None:
            assert row["last_updated_at"] <= prev  # newest-first
        prev = row["last_updated_at"]


def test_canonical_valid_and_scoped_for_tenant_a(
    live_client: TestClient, mint_token: Callable[..., str]
) -> None:
    resp = live_client.get(
        "/api/v1/canonical/store-sku-positions", headers=_bearer(mint_token(tenant_id=TENANT_A))
    )
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_canonical_valid_for_tenant_b(live_client: TestClient, mint_token: Callable[..., str]) -> None:
    resp = live_client.get(
        "/api/v1/canonical/store-sku-positions", headers=_bearer(mint_token(tenant_id=TENANT_B))
    )
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_canonical_platform_ops_sees_widened_set(
    live_client: TestClient, mint_token: Callable[..., str]
) -> None:
    token = mint_token(user_type="PLATFORM", tenant_id=None, roles=("dis:ops", "dis:read"))
    resp = live_client.get("/api/v1/canonical/store-sku-positions", headers=_bearer(token))
    assert resp.status_code == 200
    _assert_well_shaped(resp.json())


def test_canonical_requires_a_token(live_client: TestClient) -> None:
    assert live_client.get("/api/v1/canonical/store-sku-positions").status_code == 401


def test_canonical_full_column_set_store_name_bound_and_size(
    live_client: TestClient,
    mint_token: Callable[..., str],
    stack_env: dict[str, str],
    seeded_identity: Engine,
) -> None:
    """Slice 52a acceptance: full live column set (minus tenant_id, ingest_metadata) + store_name,
    the top-50 bound, newest-first order, and the size envelope — against real seeded rows.

    Seeds 55 rich rows (>50 to prove the bound clamps) for TENANT_A on a mirrored store, with a
    populated attribute_staleness_map so the jsonb + size assertion is realistic. store_name always
    resolves for a real row (the FK fk_sscp_store guarantees the store is mirrored — the null branch
    is unreachable via a valid insert and is covered at the unit layer instead).
    """
    _ = seeded_identity  # requested for its seeding side effect (identity_mirror + source_mappings)
    admin = create_engine(stack_env["POSTGRES_ADMIN_URL"])  # superuser: bypasses RLS for the seed
    try:
        with admin.begin() as conn:
            store_a = conn.execute(
                text(
                    "SELECT store_id FROM identity_mirror.stores "
                    "WHERE tenant_id = :t ORDER BY store_id LIMIT 1"
                ),
                {"t": TENANT_A},
            ).scalar_one_or_none()
            mv = conn.execute(
                text("SELECT mapping_version_id FROM config.source_mappings LIMIT 1")
            ).scalar_one_or_none()
            if store_a is None or mv is None:
                raise RuntimeError(
                    "canonical 52a test needs a seeded store for TENANT_A + a source_mapping; "
                    "bring up the stack with seed (make run-local)."
                )
            store_a_name = conn.execute(
                text("SELECT name FROM identity_mirror.stores WHERE tenant_id = :t AND store_id = :s"),
                {"t": TENANT_A, "s": store_a},
            ).scalar_one()
            # ~40-key staleness map — a realistic jsonb payload for the size assertion.
            asm = json.dumps({f"attr_{i}": "2026-06-09T09:14:41Z" for i in range(40)})
            for i in range(55):
                conn.execute(
                    _INSERT_RICH,
                    {
                        "tenant": TENANT_A,
                        "store": store_a,
                        "sku": f"{_SIZE_PREFIX}{i:03d}",
                        "mv": mv,
                        "asm": asm,
                    },
                )
            # The expected key set derived from the LIVE schema (criterion 2: not a snapshot).
            live_cols = {
                r[0]
                for r in conn.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'canonical' AND table_name = 'store_sku_current_position'"
                    )
                )
            }
        expected_keys = (live_cols - {"tenant_id", "ingest_metadata", "mapping_version_id"}) | {
            "mapping_version",
            "store_name",
        }

        resp = live_client.get(
            "/api/v1/canonical/store-sku-positions", headers=_bearer(mint_token(tenant_id=TENANT_A))
        )
        assert resp.status_code == 200
        items = resp.json()["items"]

        # Criterion 5: the top-50 bound clamps 55 seeded rows to 50, newest-first order intact.
        assert len(items) == 50
        prev: str | None = None
        for row in items:
            if prev is not None:
                assert row["last_updated_at"] <= prev
            prev = row["last_updated_at"]

        row0 = items[0]  # a seeded rich row (latest transaction => newest)
        # Criterion 2: the response carries EXACTLY the full live set minus tenant_id/ingest_metadata,
        # with mapping_version_id represented only as mapping_version, plus store_name.
        assert set(row0.keys()) == expected_keys
        assert "mapping_version" in row0
        for absent in ("tenant_id", "ingest_metadata", "mapping_version_id"):
            assert absent not in row0
        # Criterion 3 + 4: store_name resolves (FK => mirrored) and store_id remains alongside it.
        assert row0["store_id"] == str(store_a)
        assert row0["store_name"] == store_a_name
        # A representative new column renders money-safe; jsonb passes through as an object.
        assert row0["unit_cost"] == "812.5000"
        assert isinstance(row0["attribute_staleness_map"], dict)
        # Criterion 7: a single response, well under the 500KB envelope for 50 rows (incl. jsonb).
        assert len(resp.content) < 500_000
    finally:
        with admin.begin() as conn:
            conn.execute(
                text("DELETE FROM canonical.store_sku_current_position WHERE sku_id LIKE :p"),
                {"p": f"{_SIZE_PREFIX}%"},
            )
        admin.dispose()


async def test_canonical_tenant_isolation_over_canonical(
    stack_env: dict[str, str], seeded_identity: Engine
) -> None:
    """Prove tenant scoping + the store filter live: seed A + B (FK-valid), read scoped, clean.

    ``seeded_identity`` (session fixture) syncs identity_mirror (tenants + stores) and seeds a
    ``config.source_mappings`` row, so the store + mapping_version FK targets exist for the seed.
    """
    _ = seeded_identity  # requested for its seeding side effect (identity_mirror + source_mappings)
    admin_engine = create_async_engine(stack_env["POSTGRES_ADMIN_URL"])  # superuser: bypasses RLS
    rls_engine = create_rls_engine(stack_env["POSTGRES_URL"])  # NOBYPASSRLS: the real read path
    try:
        async with admin_engine.begin() as conn:
            store_a = (
                await conn.execute(
                    text("SELECT store_id FROM identity_mirror.stores WHERE tenant_id = :t LIMIT 1"),
                    {"t": TENANT_A},
                )
            ).scalar_one_or_none()
            store_b = (
                await conn.execute(
                    text("SELECT store_id FROM identity_mirror.stores WHERE tenant_id = :t LIMIT 1"),
                    {"t": TENANT_B},
                )
            ).scalar_one_or_none()
            mv = (
                await conn.execute(text("SELECT mapping_version_id FROM config.source_mappings LIMIT 1"))
            ).scalar_one_or_none()
            if store_a is None or store_b is None or mv is None:
                raise RuntimeError(
                    "canonical isolation test needs a seeded store per tenant + a source_mapping; "
                    "bring up the stack with seed (make run-local)."
                )
            await conn.execute(_INSERT, {"tenant": TENANT_A, "store": store_a, "sku": _MARK_A1, "mv": mv})
            await conn.execute(_INSERT, {"tenant": TENANT_A, "store": store_a, "sku": _MARK_A2, "mv": mv})
            await conn.execute(_INSERT, {"tenant": TENANT_B, "store": store_b, "sku": _MARK_B1, "mv": mv})

        def _skus(rows: Sequence[Row[Any]]) -> set[str]:
            return {r.sku_id for r in rows}

        a_rows = await list_positions(
            rls_engine, ReadScope(is_platform=False, tenant_id=UUID(TENANT_A)), limit=50
        )
        b_rows = await list_positions(
            rls_engine, ReadScope(is_platform=False, tenant_id=UUID(TENANT_B)), limit=50
        )
        p_rows = await list_positions(rls_engine, ReadScope(is_platform=True, tenant_id=None), limit=50)
        a_store = await list_positions(
            rls_engine, ReadScope(is_platform=False, tenant_id=UUID(TENANT_A)), limit=50, store_id=store_b
        )

        a_skus, b_skus, p_skus = _skus(a_rows), _skus(b_rows), _skus(p_rows)
        # TENANT_A sees ONLY its own; never tenant B's.
        assert {_MARK_A1, _MARK_A2} <= a_skus
        assert _MARK_B1 not in a_skus
        # TENANT_B sees ONLY its own.
        assert _MARK_B1 in b_skus
        assert _MARK_A1 not in b_skus and _MARK_A2 not in b_skus
        # PLATFORM see-all spans both tenants.
        assert {_MARK_A1, _MARK_A2, _MARK_B1} <= p_skus
        # Store filter: tenant A scoped to tenant B's store yields none of A's markers.
        assert _MARK_A1 not in _skus(a_store) and _MARK_A2 not in _skus(a_store)

        # Criterion 6 (behavioral half): the zero-leak assertion is checked against an INDEPENDENT
        # admin (RLS-bypassing) count — read directly, never through list_positions / read_session —
        # so the oracle does not reuse the query under test.
        async with admin_engine.begin() as conn:
            expected_a = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM canonical.store_sku_current_position "
                        "WHERE tenant_id = :t AND sku_id = ANY(:marks)"
                    ),
                    {"t": TENANT_A, "marks": [_MARK_A1, _MARK_A2]},
                )
            ).scalar_one()
        assert len(a_skus & {_MARK_A1, _MARK_A2}) == expected_a == 2
        assert _MARK_B1 not in a_skus  # cross-tenant leak would show here, against the independent count
        # store_name resolves for A's rows (the FK fk_sscp_store guarantees each store is mirrored).
        assert all(getattr(r, "store_name", None) is not None for r in a_rows)
    finally:
        async with admin_engine.begin() as conn:
            await conn.execute(
                text("DELETE FROM canonical.store_sku_current_position WHERE sku_id = ANY(:marks)"),
                {"marks": list(_ALL_MARKS)},
            )
        await admin_engine.dispose()
        await rls_engine.dispose()
