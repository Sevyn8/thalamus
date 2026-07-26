"""Slice 9 (one email = one identity) tests.

Covers the migration pre-flight detection helper, the post-migration
index swap, the DB global-uniqueness backstop under a TENANT (RLS-scoped)
session, and the seed loader's cross-table guard.

The migration's ``detect_email_violations`` helper is written for the
migration's SYNC bind, so it is exercised here via a sync engine. It is
loaded by file path (migration modules are not an importable package).
"""
from __future__ import annotations

import importlib.util
import pathlib
import uuid
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from admin_backend.auth.context import AuthContext
from admin_backend.config import Settings, get_settings
from admin_backend.db.session import get_tenant_session
from admin_backend.errors import EmailAlreadyExistsError
from admin_backend.models.tenant_user import ActorUserType
from admin_backend.repositories.tenant_users import TenantUsersRepo

_MIG_PATH = (
    pathlib.Path(__file__).resolve().parents[2]
    / "migrations"
    / "versions"
    / "f4b8c1d2e3a9_slice9_global_email_uniqueness.py"
)
_spec = importlib.util.spec_from_file_location("_slice9_mig", _MIG_PATH)
assert _spec is not None and _spec.loader is not None
_mig = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mig)
detect_email_violations = _mig.detect_email_violations


# ---------------------------------------------------------------------------
# Post-migration index state
# ---------------------------------------------------------------------------


async def test_email_index_is_global_after_migration(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
) -> None:
    """The per-tenant email index is gone; the global one is present."""
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        rows = await session.execute(
            text(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = :s AND tablename = 'tenant_users' "
                "AND indexname LIKE '%email%'"
            ),
            {"s": schema},
        )
        names = {r[0] for r in rows.fetchall()}
    assert "uq_tenant_users_email" in names
    assert "uq_tenant_users_tenant_email" not in names


# ---------------------------------------------------------------------------
# Migration pre-flight detection helper
# ---------------------------------------------------------------------------


def test_detect_email_violations_clean_then_flags(settings: Settings) -> None:
    """LOAD-BEARING: the pre-flight detection returns empty on a clean DB
    and flags BOTH a cross-tenant tenant_users dup and a platform/tenant
    overlap (the amit@sevyn8.com staging scenario). Violations are staged
    inside a SAVEPOINT and rolled back, so the live index is untouched."""
    schema = settings.db_schema
    engine = create_engine(settings.database_url)  # psycopg3 sync
    try:
        with engine.connect() as conn:
            # Session-scoped so it survives across savepoints. Migration
            # uses is_local=true (single tx); either makes tenant_users
            # visible under the D-29 PLATFORM OR-branch (NOBYPASSRLS role).
            conn.execute(
                text("SELECT set_config('app.user_type', 'PLATFORM', false)")
            )

            dupes0, overlaps0 = detect_email_violations(conn, schema)
            assert dupes0 == []
            assert overlaps0 == []

            tenant_ids = [
                r[0]
                for r in conn.execute(
                    text(f"SELECT id FROM {schema}.tenants LIMIT 2")
                ).fetchall()
            ]
            plat = conn.execute(
                text(f"SELECT email FROM {schema}.platform_users LIMIT 1")
            ).first()
            if len(tenant_ids) < 2 or plat is None:
                pytest.skip("needs >=2 tenants and >=1 platform_user (seed)")
            plat_email = str(plat[0])

            sp = conn.begin_nested()
            try:
                # Drop the global index so a cross-tenant dup can be staged.
                conn.execute(
                    text(f"DROP INDEX {schema}.uq_tenant_users_email")
                )
                dup_email = f"detect-dup-{uuid.uuid4().hex[:8]}@test.example.com"
                for tid in tenant_ids[:2]:
                    conn.execute(
                        text(
                            f"INSERT INTO {schema}.tenant_users "
                            "(tenant_id, email, full_name, status) VALUES "
                            "(:t, :e, 'Dup', "
                            f"CAST('INVITED' AS {schema}.tenant_user_status_enum))"
                        ),
                        {"t": tid, "e": dup_email},
                    )
                # Platform/tenant overlap: a tenant_user with a platform email.
                conn.execute(
                    text(
                        f"INSERT INTO {schema}.tenant_users "
                        "(tenant_id, email, full_name, status) VALUES "
                        "(:t, :e, 'Overlap', "
                        f"CAST('INVITED' AS {schema}.tenant_user_status_enum))"
                    ),
                    {"t": tenant_ids[0], "e": plat_email},
                )

                dupes, overlaps = detect_email_violations(conn, schema)
                assert dup_email in [email for email, _count in dupes]
                assert plat_email in overlaps
            finally:
                sp.rollback()
    finally:
        engine.dispose()


# ---------------------------------------------------------------------------
# DB global-uniqueness backstop under a TENANT (RLS-scoped) session
# ---------------------------------------------------------------------------


async def test_repo_backstop_catches_cross_tenant_under_tenant_session(
    make_tenant: Any,
    make_tenant_user: Any,
    make_platform_user: Any,
    tenant_auth_factory: Any,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """LOAD-BEARING: under a TENANT OWNER's RLS-scoped session the
    app-level tenant_users pre-check cannot see another tenant's rows, so
    the global uq_tenant_users_email index is the authoritative backstop.
    A create with an email already held in another tenant -> 409
    EmailAlreadyExistsError(side=tenant), not a 500."""
    repo = TenantUsersRepo()
    tenant_a = await make_tenant(name="Backstop-A")
    tenant_b = await make_tenant(name="Backstop-B")
    actor = await make_platform_user(
        email=f"bk-actor-{uuid.uuid4().hex[:8]}@ithina.test"
    )
    collision = f"bk-cross-{uuid.uuid4().hex[:8]}@test.example.com"
    await make_tenant_user(
        tenant_id=tenant_a.id, email=collision, status="INVITED"
    )

    tenant_b_auth = tenant_auth_factory(tenant_b.id)
    captured: EmailAlreadyExistsError | None = None
    try:
        async for session in get_tenant_session(
            tenant_b_auth, session_factory
        ):
            await repo.create(
                session,
                tenant_id=tenant_b.id,
                email=collision,
                full_name="Backstop User",
                role_assignments=[],
                actor_user_id=actor.id,
                actor_user_type=ActorUserType.PLATFORM,
            )
    except EmailAlreadyExistsError as exc:
        captured = exc

    assert captured is not None
    assert captured.context["side"] == "tenant"


# ---------------------------------------------------------------------------
# Seed loader cross-table guard
# ---------------------------------------------------------------------------


async def test_seed_loader_rejects_platform_email_collision(
    make_platform_user: Any,
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
) -> None:
    """The seed loader rejects a tenant_users email already present in
    platform_users (the cross-TABLE case the DB cannot constrain), with a
    clear message, before any INSERT."""
    from scripts.seed_dev_data.loaders.tenant_users import load
    from scripts.seed_dev_data.uuid_mapper import UUIDMapper

    email = f"seedguard-{uuid.uuid4().hex[:8]}@ithina.test"
    await make_platform_user(email=email)

    async for session in get_tenant_session(platform_auth, session_factory):
        with pytest.raises(ValueError, match="already exists in platform_users"):
            await load(session, [{"email": email}], UUIDMapper())
