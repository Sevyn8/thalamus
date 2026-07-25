"""Step 6.11.1 integration tests for TenantsRepo write methods.

16 tests in three groups:

  R-C1..R-C4: create — happy path, modules bundle, ADMIN-only,
              duplicate name.
  R-U1..R-U4: update — happy, non-existent, rename-to-taken,
              rename-to-self.
  R-T1..R-T8: transition — TRIAL/ACTIVE -> SUSPENDED, SUSPENDED -> ACTIVE
              clears suspended_* fields, invalid transitions, NOT_FOUND.

Pattern. Each test uses ``repo.create`` / ``repo.update`` /
``repo.transition`` against a PLATFORM session yielded by the
``platform_session`` fixture. ``make_platform_user`` supplies a real
``platform_users.id`` to satisfy the Pattern (a) FK on
``tenants.{created,updated,suspended,terminated}_by_user_id``.

Cleanup. The local ``cleanup_tenants`` fixture tracks IDs created
inside each test and DELETEs them at teardown — TMA rows first
(``tenant_module_access`` FK is ``ON DELETE RESTRICT``), then the
tenants row. Same approach as ``conftest.make_tenant`` but for rows
created via the new repo methods rather than the ORM fixture.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from admin_backend.auth.context import AuthContext
from admin_backend.config import get_settings
from admin_backend.db.session import get_tenant_session
from admin_backend.errors import (
    DuplicateTenantNameError,
    InvalidTenantNameForSlugError,
)
from admin_backend.models.tenant_module_access import ModuleCode
from admin_backend.repositories.onboarding import OnboardingRepo
from admin_backend.repositories.tenants import (
    TenantsRepo,
    TransitionResult,
    slug_for_tenant_root,
)


@pytest.fixture
def repo() -> TenantsRepo:
    """Stateless TenantsRepo. Safe per-test."""
    return TenantsRepo()


@pytest_asyncio.fixture
async def cleanup_tenants(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
) -> AsyncIterator[list[UUID]]:
    """Tracks tenant IDs created via ``repo.create``; DELETEs at teardown.

    Order discipline matters in two places:

    1. ``tenant_module_access`` has ``ON DELETE RESTRICT`` on ``tenant_id``,
       so its rows must go before the parent tenants row. Both DELETEs
       run inside one fresh PLATFORM session opened in teardown.

    2. Each test's signature must list ``cleanup_tenants`` AFTER
       ``make_platform_user`` and BEFORE ``platform_session`` so the
       teardown order is ``platform_session`` (commits the test's
       transaction) -> ``cleanup_tenants`` (sees the committed rows and
       DELETEs them) -> ``make_platform_user`` (no tenant FK refs left
       to platform_users; DELETE succeeds). Reordering breaks teardown
       and leaks rows.
    """
    schema = get_settings().db_schema
    created: list[UUID] = []
    yield created

    if created:
        async for session in get_tenant_session(
            platform_auth, session_factory
        ):
            await session.execute(
                text(
                    f"DELETE FROM {schema}.tenant_module_access "
                    "WHERE tenant_id = ANY(:ids)"
                ),
                {"ids": created},
            )
            # Step 6.20.1: ``repo.create`` now also inserts the tenant-root
            # org_node. Both FKs back to tenants are ON DELETE RESTRICT;
            # clear org_nodes before the tenants DELETE.
            await session.execute(
                text(
                    f"DELETE FROM {schema}.org_nodes "
                    "WHERE tenant_id = ANY(:ids)"
                ),
                {"ids": created},
            )
            # Slice 1: ``repo.create`` now provisions a 1:1
            # tenant_onboarding row (flag 5b); FK ON DELETE RESTRICT.
            # Slice 2/6: transition tests seed legal / billing / contact
            # section rows plus (Slice 6) a verified document and an invited
            # admin user (via ``_to_trial``) to pass the complete-onboarding
            # gate; all FK ON DELETE RESTRICT.
            for _t in (
                "tenant_legal_profile",
                "tenant_billing_profile",
                "tenant_contacts",
                "tenant_documents",
                "tenant_users",
                "tenant_onboarding",
            ):
                await session.execute(
                    text(
                        f"DELETE FROM {schema}.{_t} "
                        "WHERE tenant_id = ANY(:ids)"
                    ),
                    {"ids": created},
                )
            await session.execute(
                text(f"DELETE FROM {schema}.tenants WHERE id = ANY(:ids)"),
                {"ids": created},
            )


def _base_create_kwargs(name: str, actor_id: UUID) -> dict[str, Any]:
    """Minimal valid kwargs for ``repo.create``.

    Inline rather than parameterising to keep each test readable on
    its own; tests that vary modules_enabled / monthly_revenue
    override per-call.
    """
    return {
        "name": name,
        "region": "US",
        "tier": "ENTERPRISE",
        "industry": "GROCERY",
        "country": "United States",
        "primary_contact_name": "Operator",
        "contact_email": f"op-{uuid.uuid4().hex[:8]}@test.local",
        "number_of_stores": 5,
        "number_of_stores_as_of_date": date(2026, 1, 1),
        "display_code": None,
        "monthly_revenue_usd": None,
        "monthly_revenue_as_of_date": None,
        "modules_enabled": [ModuleCode.ADMIN],
        "actor_user_id": actor_id,
    }


async def _seed_required_sections(session, tenant_id, actor_id) -> None:
    """Make a tenant fully completable under the Slice-6 gate.

    Slice 2 gated ONBOARDING -> TRIAL on legal + billing + >=1 contact;
    Slice 6 (option a) adds the Auth0 organization provisioned, >=1 invited
    admin user, and documents all-verified. Sections go through
    ``OnboardingRepo``; the three new facts are direct session writes (they
    are pure DB facts, not reachable via a repo method here). ``actor_id``
    is a platform_users id, reused as the document's verified_by (FK).
    No audit emission (``auth`` / ``request_id`` omitted).
    """
    schema = get_settings().db_schema
    ob = OnboardingRepo()
    await ob.upsert_legal_profile(
        session,
        tenant_id,
        legal_entity_name="Acme Retail Private Limited",
        entity_type="PRIVATE_LIMITED",
        registration_number=None,
        incorporation_date=None,
        registered_address=None,
        actor_user_id=actor_id,
    )
    await ob.upsert_billing_profile(
        session,
        tenant_id,
        payment_terms="NET_30",
        currency="INR",
        billing_email=None,
        billing_contact_name=None,
        billing_address=None,
        actor_user_id=actor_id,
    )
    await ob.replace_contacts(
        session,
        tenant_id,
        items=[{"contact_type": "PRIMARY", "name": "Dana Ops"}],
        actor_user_id=actor_id,
    )
    # Slice 6 facts (direct writes; see test_ob1b pattern).
    await session.execute(
        text(
            f"UPDATE {schema}.tenants SET auth0_org_id = :org WHERE id = :tid"
        ),
        {"org": f"org_test_{tenant_id.hex[:12]}", "tid": tenant_id},
    )
    await session.execute(
        text(
            f"""
            INSERT INTO {schema}.tenant_users (
                tenant_id, email, full_name, status, invited_at
            ) VALUES (
                :tid, :email, 'Onboarding Admin', 'INVITED', now()
            )
            """
        ),
        {
            "tid": tenant_id,
            "email": f"admin-{tenant_id.hex[:8]}@test.example.com",
        },
    )
    await session.execute(
        text(
            f"""
            INSERT INTO {schema}.tenant_documents (
                tenant_id, document_type, gcs_object_uri,
                verification_status, verified_by_user_id, verified_at
            ) VALUES (
                :tid, 'PAN_CARD', 'gs://test/doc', 'VERIFIED', :pid, now()
            )
            """
        ),
        {"tid": tenant_id, "pid": actor_id},
    )


async def _to_trial(repo, session, tenant_id, actor_id) -> None:
    """Drive a freshly-created ONBOARDING tenant to TRIAL.

    Slice 1: ``repo.create`` now lands the tenant in ONBOARDING, so
    transition tests that start from TRIAL / ACTIVE first complete
    onboarding. Slice 2: complete-onboarding now requires legal +
    billing + >=1 contact, so seed those first. Asserts the transition
    succeeded.
    """
    await _seed_required_sections(session, tenant_id, actor_id)
    _row, result = await repo.complete_onboarding(
        session, tenant_id, actor_user_id=actor_id
    )
    assert result is TransitionResult.OK


# ============================================================================
# R-C: create
# ============================================================================


async def test_rc1_create_happy_path(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """Tenant inserted with status=ONBOARDING (Slice 1: the DDL default,
    no longer TRIAL); modules row created; audit columns populated from
    actor_user_id."""
    actor = await make_platform_user(status="ACTIVE")
    row = await repo.create(
        platform_session,
        **_base_create_kwargs("RC1-Acme", actor.id),
    )
    cleanup_tenants.append(row.tenant.id)

    assert row.tenant.name == "RC1-Acme"
    assert row.tenant.status.value == "ONBOARDING"
    assert row.tenant.created_by_user_id == actor.id
    assert row.tenant.updated_by_user_id == actor.id
    assert row.tenant.suspended_at is None
    assert row.num_stores == 0  # no real stores yet
    assert {m["code"] for m in row.modules} == {"ADMIN"}


async def test_rc2_create_with_modules_bundle(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """modules_enabled inserts a tenant_module_access row per module."""
    actor = await make_platform_user(status="ACTIVE")
    kwargs = _base_create_kwargs("RC2-Mods", actor.id)
    kwargs["modules_enabled"] = [
        ModuleCode.ADMIN,
        ModuleCode.PRICING_OS,
        ModuleCode.PERISHABLES_ASSISTANT,
    ]
    row = await repo.create(platform_session, **kwargs)
    cleanup_tenants.append(row.tenant.id)

    codes = {m["code"] for m in row.modules}
    assert codes == {"ADMIN", "PRICING_OS", "PERISHABLES_ASSISTANT"}


async def test_rc3_create_admin_only_when_modules_empty_at_repo(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """Caller is responsible for ADMIN-force at the schema layer; the
    repo trusts the input. Passing [ADMIN] only produces one row."""
    actor = await make_platform_user(status="ACTIVE")
    kwargs = _base_create_kwargs("RC3-AdminOnly", actor.id)
    kwargs["modules_enabled"] = [ModuleCode.ADMIN]
    row = await repo.create(platform_session, **kwargs)
    cleanup_tenants.append(row.tenant.id)

    assert {m["code"] for m in row.modules} == {"ADMIN"}


async def test_rc4_create_duplicate_name_raises(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """Two creates with the same name -> DuplicateTenantNameError."""
    actor = await make_platform_user(status="ACTIVE")
    first = await repo.create(
        platform_session,
        **_base_create_kwargs("RC4-DupName", actor.id),
    )
    cleanup_tenants.append(first.tenant.id)

    with pytest.raises(DuplicateTenantNameError):
        await repo.create(
            platform_session,
            **_base_create_kwargs("RC4-DupName", actor.id),
        )


# ============================================================================
# R-U: update
# ============================================================================


async def test_ru1_update_happy_path(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """PATCH a subset of fields; updated_by_user_id flips; trigger
    refreshes updated_at."""
    actor = await make_platform_user(status="ACTIVE")
    second_actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session,
        **_base_create_kwargs("RU1-Original", actor.id),
    )
    cleanup_tenants.append(created.tenant.id)

    updated = await repo.update(
        platform_session,
        created.tenant.id,
        fields={
            "primary_contact_name": "New Operator",
            "monthly_revenue_usd": Decimal("12345.67"),
            "monthly_revenue_as_of_date": date(2026, 2, 1),
        },
        actor_user_id=second_actor.id,
    )
    assert updated is not None
    assert updated.tenant.primary_contact_name == "New Operator"
    assert updated.tenant.monthly_revenue_usd == Decimal("12345.67")
    assert updated.tenant.updated_by_user_id == second_actor.id
    # created_by_user_id unchanged.
    assert updated.tenant.created_by_user_id == actor.id


async def test_ru2_update_non_existent_returns_none(
    repo, make_platform_user, platform_session,
) -> None:
    """RLS-as-404 per D-17: missing/filtered row -> repo returns None."""
    actor = await make_platform_user(status="ACTIVE")
    missing_id = uuid.uuid4()
    result = await repo.update(
        platform_session,
        missing_id,
        fields={"primary_contact_name": "X"},
        actor_user_id=actor.id,
    )
    assert result is None


async def test_ru3_update_rename_to_taken_raises(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """Rename to a name another tenant already holds -> 409."""
    actor = await make_platform_user(status="ACTIVE")
    first = await repo.create(
        platform_session, **_base_create_kwargs("RU3-FirstName", actor.id)
    )
    cleanup_tenants.append(first.tenant.id)
    second = await repo.create(
        platform_session, **_base_create_kwargs("RU3-SecondName", actor.id)
    )
    cleanup_tenants.append(second.tenant.id)

    with pytest.raises(DuplicateTenantNameError):
        await repo.update(
            platform_session,
            second.tenant.id,
            fields={"name": "RU3-FirstName"},
            actor_user_id=actor.id,
        )


async def test_ru4_update_rename_to_self_succeeds(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """PATCH a row's name to its current value is a no-op success
    (the duplicate check excludes self by id)."""
    actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session,
        **_base_create_kwargs("RU4-SameName", actor.id),
    )
    cleanup_tenants.append(created.tenant.id)

    updated = await repo.update(
        platform_session,
        created.tenant.id,
        fields={"name": "RU4-SameName"},
        actor_user_id=actor.id,
    )
    assert updated is not None
    assert updated.tenant.name == "RU4-SameName"


# ============================================================================
# R-T: transition
# ============================================================================


async def test_rt1_trial_to_suspended_populates_suspended_columns(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """TRIAL -> SUSPENDED: status flips; suspended_at + suspended_by_user_id set."""
    actor = await make_platform_user(status="ACTIVE")
    suspending_actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session, **_base_create_kwargs("RT1-Trial", actor.id)
    )
    cleanup_tenants.append(created.tenant.id)
    assert created.tenant.status.value == "ONBOARDING"
    await _to_trial(repo, platform_session, created.tenant.id, actor.id)

    row, result = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="SUSPENDED",
        actor_user_id=suspending_actor.id,
    )
    assert result is TransitionResult.OK
    assert row is not None
    assert row.tenant.status.value == "SUSPENDED"
    assert row.tenant.suspended_at is not None
    assert row.tenant.suspended_by_user_id == suspending_actor.id
    assert row.tenant.updated_by_user_id == suspending_actor.id


async def test_rt2_active_to_suspended(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """ACTIVE -> SUSPENDED works."""
    actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session, **_base_create_kwargs("RT2-Active", actor.id)
    )
    cleanup_tenants.append(created.tenant.id)
    await _to_trial(repo, platform_session, created.tenant.id, actor.id)
    # Lift to ACTIVE first.
    _row, result_act = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="ACTIVE",
        actor_user_id=actor.id,
    )
    assert result_act is TransitionResult.OK

    row, result = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="SUSPENDED",
        actor_user_id=actor.id,
    )
    assert result is TransitionResult.OK
    assert row is not None
    assert row.tenant.status.value == "SUSPENDED"


async def test_rt3_suspended_to_suspended_invalid(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """SUSPENDED -> SUSPENDED returns INVALID_STATE."""
    actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session, **_base_create_kwargs("RT3-Susp", actor.id)
    )
    cleanup_tenants.append(created.tenant.id)
    await _to_trial(repo, platform_session, created.tenant.id, actor.id)
    # Transition into SUSPENDED.
    _row, result_susp = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="SUSPENDED",
        actor_user_id=actor.id,
    )
    assert result_susp is TransitionResult.OK
    # Re-suspending should not be allowed.
    row, result = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="SUSPENDED",
        actor_user_id=actor.id,
    )
    assert result is TransitionResult.INVALID_STATE
    assert row is None


async def test_rt4_trial_to_active(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """TRIAL -> ACTIVE works."""
    actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session, **_base_create_kwargs("RT4-Trial", actor.id)
    )
    cleanup_tenants.append(created.tenant.id)
    await _to_trial(repo, platform_session, created.tenant.id, actor.id)

    row, result = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="ACTIVE",
        actor_user_id=actor.id,
    )
    assert result is TransitionResult.OK
    assert row is not None
    assert row.tenant.status.value == "ACTIVE"
    assert row.tenant.suspended_at is None


async def test_rt5_suspended_to_active_clears_suspended_columns(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """SUSPENDED -> ACTIVE: status flips AND suspended_*=NULL (ck_*_consistency)."""
    actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session, **_base_create_kwargs("RT5-SuspAct", actor.id)
    )
    cleanup_tenants.append(created.tenant.id)
    await _to_trial(repo, platform_session, created.tenant.id, actor.id)
    # Suspend first.
    _r, _x = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="SUSPENDED",
        actor_user_id=actor.id,
    )
    # Activate.
    row, result = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="ACTIVE",
        actor_user_id=actor.id,
    )
    assert result is TransitionResult.OK
    assert row is not None
    assert row.tenant.status.value == "ACTIVE"
    assert row.tenant.suspended_at is None
    assert row.tenant.suspended_by_user_id is None


async def test_rt6_active_to_active_invalid(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """ACTIVE -> ACTIVE returns INVALID_STATE."""
    actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session, **_base_create_kwargs("RT6-Act", actor.id)
    )
    cleanup_tenants.append(created.tenant.id)
    await _to_trial(repo, platform_session, created.tenant.id, actor.id)
    _row, _r = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="ACTIVE",
        actor_user_id=actor.id,
    )

    row, result = await repo.transition(
        platform_session,
        created.tenant.id,
        target_status="ACTIVE",
        actor_user_id=actor.id,
    )
    assert result is TransitionResult.INVALID_STATE
    assert row is None


async def test_rt7_transition_missing_id_returns_not_found(
    repo, make_platform_user, platform_session,
) -> None:
    """Missing/filtered tenant -> NOT_FOUND."""
    actor = await make_platform_user(status="ACTIVE")
    missing_id = uuid.uuid4()
    row, result = await repo.transition(
        platform_session,
        missing_id,
        target_status="SUSPENDED",
        actor_user_id=actor.id,
    )
    assert result is TransitionResult.NOT_FOUND
    assert row is None


async def test_rt8_trial_to_active_then_active_to_suspended_to_active(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """Full lifecycle round-trip: TRIAL -> ACTIVE -> SUSPENDED -> ACTIVE.

    Each leg preserves the invariant that ACTIVE has suspended_* NULL.
    """
    actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session,
        **_base_create_kwargs("RT8-Cycle", actor.id),
    )
    cleanup_tenants.append(created.tenant.id)
    await _to_trial(repo, platform_session, created.tenant.id, actor.id)

    _r1, ok1 = await repo.transition(
        platform_session, created.tenant.id,
        target_status="ACTIVE", actor_user_id=actor.id,
    )
    assert ok1 is TransitionResult.OK

    _r2, ok2 = await repo.transition(
        platform_session, created.tenant.id,
        target_status="SUSPENDED", actor_user_id=actor.id,
    )
    assert ok2 is TransitionResult.OK

    row3, ok3 = await repo.transition(
        platform_session, created.tenant.id,
        target_status="ACTIVE", actor_user_id=actor.id,
    )
    assert ok3 is TransitionResult.OK
    assert row3 is not None
    assert row3.tenant.status.value == "ACTIVE"
    assert row3.tenant.suspended_at is None
    assert row3.tenant.suspended_by_user_id is None


# ============================================================================
# R-OR: tenant-root org_node side-effect of repo.create (Step 6.20.1)
# ============================================================================


async def test_create_inserts_tenant_root_org_node(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """LOAD-BEARING: after ``repo.create``, exactly one
    ``(node_type='TENANT', parent_id IS NULL, status='ACTIVE')`` row
    exists in ``core.org_nodes`` for the new tenant.

    Locks the contract at the seam. A future refactor that splits
    ``create()`` across helpers cannot silently drop the org_node
    insert without this test failing. Asserts the (code, path) derived
    by re-calling the slug helper rather than hardcoding strings (per
    the "deliberately not added" note in the impl prompt: avoids
    duplicating the slug rule into a brittle change-detector).
    """
    actor = await make_platform_user(status="ACTIVE")
    name = "ROR1-Acme"
    created = await repo.create(
        platform_session,
        **_base_create_kwargs(name, actor.id),
    )
    cleanup_tenants.append(created.tenant.id)

    expected_code, expected_path = slug_for_tenant_root(name, None)

    schema = get_settings().db_schema
    row = (
        await platform_session.execute(
            text(
                f"""
                SELECT id, tenant_id, parent_id, node_type, status,
                       code, path::text AS path_text
                FROM {schema}.org_nodes
                WHERE tenant_id = :tid
                """
            ),
            {"tid": created.tenant.id},
        )
    ).all()

    assert len(row) == 1, f"expected exactly 1 org_node row, got {len(row)}"
    only = row[0]
    assert only.parent_id is None
    assert only.node_type == "TENANT"
    assert only.status == "ACTIVE"
    assert only.code == expected_code
    assert only.path_text == expected_path


async def test_create_org_node_uses_actor_pattern_b(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """Pattern (b) per D-13 / LD7: org_node row carries both the actor
    UUID and the discriminator ``'PLATFORM'`` on both audit-actor pairs.
    """
    actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session,
        **_base_create_kwargs("ROR2-Audit", actor.id),
    )
    cleanup_tenants.append(created.tenant.id)

    schema = get_settings().db_schema
    row = (
        await platform_session.execute(
            text(
                f"""
                SELECT created_by_user_id, created_by_user_type,
                       updated_by_user_id, updated_by_user_type
                FROM {schema}.org_nodes
                WHERE tenant_id = :tid
                """
            ),
            {"tid": created.tenant.id},
        )
    ).one()

    assert row.created_by_user_id == actor.id
    assert row.created_by_user_type == "PLATFORM"
    assert row.updated_by_user_id == actor.id
    assert row.updated_by_user_type == "PLATFORM"


async def test_create_org_node_name_matches_tenant_name(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """``org_nodes.name`` mirrors ``tenants.name`` per LD8 (matches
    seed shape: Buc-ee's tenant has org_node name 'Buc-ee's').
    """
    actor = await make_platform_user(status="ACTIVE")
    tenant_name = "ROR3-Some Co"
    created = await repo.create(
        platform_session,
        **_base_create_kwargs(tenant_name, actor.id),
    )
    cleanup_tenants.append(created.tenant.id)

    schema = get_settings().db_schema
    row = (
        await platform_session.execute(
            text(
                f"SELECT name FROM {schema}.org_nodes "
                "WHERE tenant_id = :tid"
            ),
            {"tid": created.tenant.id},
        )
    ).one()

    assert row.name == tenant_name


async def test_create_with_display_code_uses_display_code_for_slug(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """When ``display_code`` is supplied, the org_node's ``(code, path)``
    derives from it, not from ``name``.
    """
    actor = await make_platform_user(status="ACTIVE")
    kwargs = _base_create_kwargs("ROR4-Some Long Tenant Name", actor.id)
    kwargs["display_code"] = "custom-code"
    created = await repo.create(platform_session, **kwargs)
    cleanup_tenants.append(created.tenant.id)

    schema = get_settings().db_schema
    row = (
        await platform_session.execute(
            text(
                f"SELECT code, path::text AS path_text FROM {schema}.org_nodes "
                "WHERE tenant_id = :tid"
            ),
            {"tid": created.tenant.id},
        )
    ).one()

    assert row.code == "CUSTOM-CODE"
    assert row.path_text == "custom_code"


async def test_create_empty_slug_rejects_no_tenant_inserted(
    repo, make_platform_user, platform_session
) -> None:
    """Empty-slug name -> ``InvalidTenantNameForSlugError`` (422). The
    slug call happens BEFORE the tenants INSERT (refined LD2), so the
    error leaves no row behind in ``tenants``.

    No ``cleanup_tenants`` fixture: the slug error fires before any
    INSERT runs; nothing to clean.
    """
    actor = await make_platform_user(status="ACTIVE")
    kwargs = _base_create_kwargs("!!!", actor.id)

    with pytest.raises(InvalidTenantNameForSlugError):
        await repo.create(platform_session, **kwargs)

    schema = get_settings().db_schema
    count = (
        await platform_session.execute(
            text(f"SELECT count(*) FROM {schema}.tenants WHERE name = :n"),
            {"n": "!!!"},
        )
    ).scalar_one()
    assert count == 0


# ============================================================================
# R-CO: complete_onboarding (Slice 1)
# ============================================================================


async def test_rco1_create_provisions_tenant_onboarding_row(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """create() provisions the 1:1 tenant_onboarding row (flag 5b):
    present, section_status '{}', completed_* NULL."""
    actor = await make_platform_user(status="ACTIVE")
    row = await repo.create(
        platform_session, **_base_create_kwargs("RCO1-Prov", actor.id)
    )
    cleanup_tenants.append(row.tenant.id)

    schema = get_settings().db_schema
    ob = (
        await platform_session.execute(
            text(
                f"SELECT section_status, completed_at, completed_by_user_id "
                f"FROM {schema}.tenant_onboarding WHERE tenant_id = :tid"
            ),
            {"tid": row.tenant.id},
        )
    ).one()
    assert ob.section_status == {}
    assert ob.completed_at is None
    assert ob.completed_by_user_id is None


async def test_rco2_complete_onboarding_flips_status_and_stamps(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """ONBOARDING -> TRIAL; tenant_onboarding.completed_* stamped."""
    actor = await make_platform_user(status="ACTIVE")
    completing_actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session, **_base_create_kwargs("RCO2-Complete", actor.id)
    )
    cleanup_tenants.append(created.tenant.id)
    # Slice 2: complete-onboarding requires legal + billing + >=1 contact.
    await _seed_required_sections(
        platform_session, created.tenant.id, actor.id
    )

    row, result = await repo.complete_onboarding(
        platform_session,
        created.tenant.id,
        actor_user_id=completing_actor.id,
    )
    assert result is TransitionResult.OK
    assert row is not None
    assert row.tenant.status.value == "TRIAL"
    assert row.tenant.updated_by_user_id == completing_actor.id

    schema = get_settings().db_schema
    ob = (
        await platform_session.execute(
            text(
                f"SELECT completed_at, completed_by_user_id "
                f"FROM {schema}.tenant_onboarding WHERE tenant_id = :tid"
            ),
            {"tid": created.tenant.id},
        )
    ).one()
    assert ob.completed_at is not None
    assert ob.completed_by_user_id == completing_actor.id


async def test_rco3_complete_onboarding_on_non_onboarding_invalid(
    repo, make_platform_user, cleanup_tenants, platform_session
) -> None:
    """Second complete_onboarding (already TRIAL) -> INVALID_STATE."""
    actor = await make_platform_user(status="ACTIVE")
    created = await repo.create(
        platform_session, **_base_create_kwargs("RCO3-Twice", actor.id)
    )
    cleanup_tenants.append(created.tenant.id)
    await _to_trial(repo, platform_session, created.tenant.id, actor.id)

    row, result = await repo.complete_onboarding(
        platform_session, created.tenant.id, actor_user_id=actor.id
    )
    assert result is TransitionResult.INVALID_STATE
    assert row is None


async def test_rco4_complete_onboarding_missing_id_not_found(
    repo, make_platform_user, platform_session
) -> None:
    """Missing / RLS-filtered tenant -> NOT_FOUND."""
    actor = await make_platform_user(status="ACTIVE")
    row, result = await repo.complete_onboarding(
        platform_session, uuid.uuid4(), actor_user_id=actor.id
    )
    assert result is TransitionResult.NOT_FOUND
    assert row is None
