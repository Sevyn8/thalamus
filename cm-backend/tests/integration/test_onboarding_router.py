"""Integration tests for the client-onboarding wizard (Slice 2).

Covers the four section resources (legal profile, tax registrations,
billing profile, contacts), the onboarding-state resource, the
complete-onboarding section-gating matrix, lookup-code + section-key
validation, gate denials, 404s, upsert idempotency, 1:N full-replace
semantics, and audit emission for every new audited route.
"""
from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any
from uuid import UUID

import pytest
import pytest_asyncio
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from admin_backend.auth.context import AuthContext
from admin_backend.auth.testing import make_test_jwt
from admin_backend.config import Settings, get_settings
from admin_backend.db.session import get_tenant_session
from admin_backend.main import create_app
from admin_backend.models.tenant import TenantStatus

from tests.integration.conftest import seed_completion_facts


pytestmark = pytest.mark.asyncio


_ONBOARDING_TABLES = (
    "tenant_legal_profile",
    "tenant_tax_registrations",
    "tenant_billing_profile",
    "tenant_contacts",
    "tenant_documents",
    "tenant_onboarding",
    # Slice 6: seed_completion_facts inserts an invited tenant_users row;
    # clear it before the make_tenant teardown deletes the tenant (FK
    # ON DELETE RESTRICT).
    "tenant_users",
)


@pytest.fixture
def app_client(
    settings: Settings, engine: Any, session_factory: Any
) -> Iterator[TestClient]:
    from admin_backend.auth.stub import StubAuthClient

    app_obj = create_app()
    app_obj.state.settings = settings
    app_obj.state.engine = engine
    app_obj.state.session_factory = session_factory
    app_obj.state.auth_client = StubAuthClient(settings)
    with TestClient(app_obj) as client:
        yield client


@pytest_asyncio.fixture
async def cleanup_onboarding(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
) -> AsyncIterator[list[UUID]]:
    """Tracks tenant IDs whose onboarding child rows a test wrote; DELETEs
    them at teardown so the ``make_tenant`` teardown's tenant DELETE (FK
    ON DELETE RESTRICT) succeeds. List ``make_tenant`` BEFORE this fixture
    in test signatures so this tears down first."""
    schema = get_settings().db_schema
    tracked: list[UUID] = []
    yield tracked
    if tracked:
        async for session in get_tenant_session(
            platform_auth, session_factory
        ):
            for tbl in _ONBOARDING_TABLES:
                await session.execute(
                    text(
                        f"DELETE FROM {schema}.{tbl} "
                        "WHERE tenant_id = ANY(:ids)"
                    ),
                    {"ids": tracked},
                )


def _auth(jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt}"}


def _tenant_jwt(settings: Settings, tenant_id: UUID) -> str:
    return make_test_jwt(
        settings, user_id=uuid.uuid4(), user_type="TENANT", tenant_id=tenant_id
    )


async def _audit_actions(
    session_factory: async_sessionmaker[AsyncSession],
    platform_auth: AuthContext,
    tenant_id: UUID,
) -> list[str]:
    """Return the action codes emitted to tenant_activity_audit_logs for
    a tenant, oldest-first."""
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        result = await session.execute(
            text(
                f"SELECT action, result_type FROM "
                f"{schema}.tenant_activity_audit_logs "
                "WHERE tenant_id = :tid ORDER BY timestamp, id"
            ),
            {"tid": tenant_id},
        )
        return [f"{r.action}:{r.result_type}" for r in result]
    raise AssertionError("unreachable")  # pragma: no cover


_LEGAL_BODY = {
    "legal_entity_name": "Acme Retail Private Limited",
    "entity_type": "PRIVATE_LIMITED",
    "registration_number": "U12345MH2020PTC000000",
    "registered_address": "1 Market Road",
}
_BILLING_BODY = {
    "payment_terms": "NET_30",
    "currency": "INR",
    "billing_email": "billing@acme.example.com",
}
_CONTACT_BODY = {"items": [{"contact_type": "PRIMARY", "name": "Dana Ops"}]}


async def _seed_sections_only(
    app_client: TestClient, jwt: str, tenant_id: UUID
) -> None:
    """PUT legal + billing + one contact (the Slice-2 section rows)."""
    assert app_client.put(
        f"/api/v1/tenants/{tenant_id}/legal-profile",
        json=_LEGAL_BODY,
        headers=_auth(jwt),
    ).status_code == 200
    assert app_client.put(
        f"/api/v1/tenants/{tenant_id}/billing-profile",
        json=_BILLING_BODY,
        headers=_auth(jwt),
    ).status_code == 200
    assert app_client.put(
        f"/api/v1/tenants/{tenant_id}/contacts",
        json=_CONTACT_BODY,
        headers=_auth(jwt),
    ).status_code == 200


async def _seed_required_sections(
    app_client: TestClient, jwt: str, tenant_id: UUID
) -> None:
    """Make a tenant fully completable under the Slice-6 gate: the section
    rows (legal + billing + contact) via the API, plus the three DB-only
    facts (Auth0 org, invited admin, verified document) via
    seed_completion_facts."""
    await _seed_sections_only(app_client, jwt, tenant_id)
    await seed_completion_facts(app_client, tenant_id)


# ===========================================================================
# Legal profile (LP)
# ===========================================================================


async def test_lp1_put_then_get_roundtrip(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    tenant = await make_tenant(name="LP1")
    cleanup_onboarding.append(tenant.id)
    put = app_client.put(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        json=_LEGAL_BODY,
        headers=_auth(super_admin_jwt),
    )
    assert put.status_code == 200, put.text
    assert put.json()["entity_type"] == "PRIVATE_LIMITED"

    got = app_client.get(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        headers=_auth(super_admin_jwt),
    )
    assert got.status_code == 200
    assert got.json()["legal_entity_name"] == "Acme Retail Private Limited"


async def test_lp2_get_absent_returns_404_section_not_found(
    app_client, super_admin_jwt, make_tenant
) -> None:
    tenant = await make_tenant(name="LP2")
    resp = app_client.get(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "SECTION_NOT_FOUND"


async def test_lp3_upsert_idempotent(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """LOAD-BEARING: a second PUT updates the same 1:1 row (no duplicate)."""
    tenant = await make_tenant(name="LP3")
    cleanup_onboarding.append(tenant.id)
    app_client.put(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        json=_LEGAL_BODY,
        headers=_auth(super_admin_jwt),
    )
    updated = {**_LEGAL_BODY, "legal_entity_name": "Acme Renamed LLP",
               "entity_type": "LLP"}
    put2 = app_client.put(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        json=updated,
        headers=_auth(super_admin_jwt),
    )
    assert put2.status_code == 200
    assert put2.json()["entity_type"] == "LLP"
    got = app_client.get(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        headers=_auth(super_admin_jwt),
    )
    assert got.json()["legal_entity_name"] == "Acme Renamed LLP"


async def test_lp4_invalid_entity_type_returns_422_named(
    app_client, super_admin_jwt, make_tenant
) -> None:
    """LOAD-BEARING: invalid lookup code -> 422 naming the field."""
    tenant = await make_tenant(name="LP4")
    resp = app_client.put(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        json={**_LEGAL_BODY, "entity_type": "NOT_A_REAL_TYPE"},
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 422
    body = resp.json()
    assert body["code"] == "INVALID_LOOKUP_CODE"
    assert "entity_type" in body["message"]


async def test_lp5_tenant_jwt_denied_403(
    app_client, settings, make_tenant
) -> None:
    """LOAD-BEARING: TENANT JWT -> 403 PLATFORM_AUDIENCE_REQUIRED on a
    section write."""
    tenant = await make_tenant(name="LP5")
    resp = app_client.put(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        json=_LEGAL_BODY,
        headers=_auth(_tenant_jwt(settings, tenant.id)),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "PLATFORM_AUDIENCE_REQUIRED"


async def test_lp6_unknown_tenant_returns_404_tenant_not_found(
    app_client, super_admin_jwt
) -> None:
    resp = app_client.put(
        f"/api/v1/tenants/{uuid.uuid4()}/legal-profile",
        json=_LEGAL_BODY,
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "TENANT_NOT_FOUND"


async def test_lp7_put_emits_one_audit_event(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding,
    session_factory, platform_auth,
) -> None:
    """LOAD-BEARING: a section PUT emits exactly one UPSERT_LEGAL_PROFILE
    success audit row."""
    tenant = await make_tenant(name="LP7")
    cleanup_onboarding.append(tenant.id)
    app_client.put(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        json=_LEGAL_BODY,
        headers=_auth(super_admin_jwt),
    )
    actions = await _audit_actions(session_factory, platform_auth, tenant.id)
    assert actions == ["UPSERT_LEGAL_PROFILE:SUCCESS"]


# ===========================================================================
# Tax registrations (TX)
# ===========================================================================


async def test_tx1_full_replace_semantics(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """LOAD-BEARING: PUT replaces the whole set; multi-state GSTIN allowed."""
    tenant = await make_tenant(name="TX1")
    cleanup_onboarding.append(tenant.id)
    first = {
        "items": [
            {"registration_type": "PAN", "registration_number": "ABCDE1234F"},
            {"registration_type": "GSTIN",
             "registration_number": "27ABCDE1234F1Z5",
             "jurisdiction": "Maharashtra"},
            {"registration_type": "GSTIN",
             "registration_number": "29ABCDE1234F1Z1",
             "jurisdiction": "Karnataka"},
        ]
    }
    r1 = app_client.put(
        f"/api/v1/tenants/{tenant.id}/tax-registrations",
        json=first, headers=_auth(super_admin_jwt),
    )
    assert r1.status_code == 200, r1.text
    assert len(r1.json()["items"]) == 3

    # Replace with a smaller set: the old GSTINs are gone.
    second = {"items": [
        {"registration_type": "PAN", "registration_number": "ZZZZZ9999Z"}
    ]}
    r2 = app_client.put(
        f"/api/v1/tenants/{tenant.id}/tax-registrations",
        json=second, headers=_auth(super_admin_jwt),
    )
    assert r2.status_code == 200
    got = app_client.get(
        f"/api/v1/tenants/{tenant.id}/tax-registrations",
        headers=_auth(super_admin_jwt),
    ).json()["items"]
    assert len(got) == 1
    assert got[0]["registration_number"] == "ZZZZZ9999Z"


async def test_tx2_in_payload_duplicate_returns_422(
    app_client, super_admin_jwt, make_tenant
) -> None:
    """LOAD-BEARING: duplicate (type, number) in one payload -> 422 before
    any DB write."""
    tenant = await make_tenant(name="TX2")
    dup = {"items": [
        {"registration_type": "PAN", "registration_number": "ABCDE1234F"},
        {"registration_type": "PAN", "registration_number": "ABCDE1234F"},
    ]}
    resp = app_client.put(
        f"/api/v1/tenants/{tenant.id}/tax-registrations",
        json=dup, headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "DUPLICATE_SECTION_ROW"


async def test_tx3_invalid_registration_type_returns_422(
    app_client, super_admin_jwt, make_tenant
) -> None:
    tenant = await make_tenant(name="TX3")
    resp = app_client.put(
        f"/api/v1/tenants/{tenant.id}/tax-registrations",
        json={"items": [
            {"registration_type": "BOGUS", "registration_number": "X"}
        ]},
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_LOOKUP_CODE"


async def test_tx5_replace_emits_single_audit_event(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding,
    session_factory, platform_auth,
) -> None:
    """LOAD-BEARING: a 3-row replace emits ONE audit event, not per row."""
    tenant = await make_tenant(name="TX5")
    cleanup_onboarding.append(tenant.id)
    app_client.put(
        f"/api/v1/tenants/{tenant.id}/tax-registrations",
        json={"items": [
            {"registration_type": "PAN", "registration_number": "ABCDE1234F"},
            {"registration_type": "VAT", "registration_number": "VAT-1"},
            {"registration_type": "EIN", "registration_number": "EIN-1"},
        ]},
        headers=_auth(super_admin_jwt),
    )
    actions = await _audit_actions(session_factory, platform_auth, tenant.id)
    assert actions == ["REPLACE_TAX_REGISTRATIONS:SUCCESS"]


# ===========================================================================
# Billing profile (BP) + Contacts (CT)
# ===========================================================================


async def test_bp1_put_get_and_invalid_codes(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    tenant = await make_tenant(name="BP1")
    cleanup_onboarding.append(tenant.id)
    put = app_client.put(
        f"/api/v1/tenants/{tenant.id}/billing-profile",
        json=_BILLING_BODY, headers=_auth(super_admin_jwt),
    )
    assert put.status_code == 200, put.text
    assert put.json()["currency"] == "INR"

    bad_curr = app_client.put(
        f"/api/v1/tenants/{tenant.id}/billing-profile",
        json={**_BILLING_BODY, "currency": "XXX"},
        headers=_auth(super_admin_jwt),
    )
    assert bad_curr.status_code == 422
    assert bad_curr.json()["code"] == "INVALID_LOOKUP_CODE"
    assert "currency" in bad_curr.json()["message"]

    bad_terms = app_client.put(
        f"/api/v1/tenants/{tenant.id}/billing-profile",
        json={**_BILLING_BODY, "payment_terms": "WHENEVER"},
        headers=_auth(super_admin_jwt),
    )
    assert bad_terms.status_code == 422
    assert "payment_terms" in bad_terms.json()["message"]


async def test_ct1_full_replace_and_invalid_type(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    tenant = await make_tenant(name="CT1")
    cleanup_onboarding.append(tenant.id)
    put = app_client.put(
        f"/api/v1/tenants/{tenant.id}/contacts",
        json={"items": [
            {"contact_type": "PRIMARY", "name": "A",
             "email": "a@x.example.com"},
            {"contact_type": "BILLING", "name": "B"},
        ]},
        headers=_auth(super_admin_jwt),
    )
    assert put.status_code == 200, put.text
    assert len(put.json()["items"]) == 2

    bad = app_client.put(
        f"/api/v1/tenants/{tenant.id}/contacts",
        json={"items": [{"contact_type": "FRIEND", "name": "C"}]},
        headers=_auth(super_admin_jwt),
    )
    assert bad.status_code == 422
    assert bad.json()["code"] == "INVALID_LOOKUP_CODE"


async def test_ct2_exact_duplicate_contact_returns_422(
    app_client, super_admin_jwt, make_tenant
) -> None:
    tenant = await make_tenant(name="CT2")
    resp = app_client.put(
        f"/api/v1/tenants/{tenant.id}/contacts",
        json={"items": [
            {"contact_type": "PRIMARY", "name": "Same"},
            {"contact_type": "PRIMARY", "name": "Same"},
        ]},
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "DUPLICATE_SECTION_ROW"


# ===========================================================================
# Onboarding state (OB)
# ===========================================================================


async def test_ob1_get_shape_and_auth0_false_until_provisioned(
    app_client, super_admin_jwt, make_tenant
) -> None:
    """LOAD-BEARING: onboarding-state shape; auth0_organization is FALSE for
    a fresh tenant (Slice 5 option a: derived from tenants.auth0_org_id,
    which is NULL until provision-auth0 stamps it)."""
    tenant = await make_tenant(name="OB1")
    resp = app_client.get(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert set(body.keys()) == {
        "current_step", "section_status", "completed_at",
        "completed_by_user_id", "sections_present", "provisioning",
    }
    assert body["provisioning"]["auth0_organization"] == "FALSE"
    assert body["provisioning"]["admin_invited"] == "FALSE"
    assert body["sections_present"] == {
        "legal": False, "tax": False, "billing": False,
        "contacts": False,
        # Slice 3: documents is a verification-status counts block.
        "documents": {
            "total": 0, "pending_review": 0, "verified": 0,
            "rejected": 0, "all_verified": False,
        },
    }
    assert body["current_step"] is None
    assert body["completed_at"] is None


async def test_ob1b_auth0_organization_true_when_org_id_stamped(
    app_client, super_admin_jwt, make_tenant,
    session_factory, platform_auth,
) -> None:
    """LOAD-BEARING (Slice 5 option a): auth0_organization derives TRUE once
    tenants.auth0_org_id is set (what provision-auth0 stamps)."""
    tenant = await make_tenant(name="OB1B")
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        await session.execute(
            text(
                f"UPDATE {schema}.tenants SET auth0_org_id = :org "
                "WHERE id = :id"
            ),
            {"org": "org_abc123", "id": tenant.id},
        )
    body = app_client.get(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        headers=_auth(super_admin_jwt),
    ).json()
    assert body["provisioning"]["auth0_organization"] == "TRUE"


async def test_ob2_presence_flags_reflect_saved_sections(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    tenant = await make_tenant(name="OB2")
    cleanup_onboarding.append(tenant.id)
    app_client.put(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        json=_LEGAL_BODY, headers=_auth(super_admin_jwt),
    )
    app_client.put(
        f"/api/v1/tenants/{tenant.id}/contacts",
        json=_CONTACT_BODY, headers=_auth(super_admin_jwt),
    )
    body = app_client.get(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        headers=_auth(super_admin_jwt),
    ).json()
    assert body["sections_present"]["legal"] is True
    assert body["sections_present"]["contacts"] is True
    assert body["sections_present"]["billing"] is False


async def test_ob3_admin_invited_true_when_invited_at_set(
    app_client, super_admin_jwt, make_tenant, make_tenant_user,
    session_factory, platform_auth,
) -> None:
    """LOAD-BEARING: admin_invited derives from tenant_users.invited_at."""
    tenant = await make_tenant(name="OB3")
    tu = await make_tenant_user(tenant_id=tenant.id, status="INVITED")
    schema = get_settings().db_schema
    async for session in get_tenant_session(platform_auth, session_factory):
        await session.execute(
            text(
                f"UPDATE {schema}.tenant_users SET invited_at = now() "
                "WHERE id = :id"
            ),
            {"id": tu.id},
        )
    body = app_client.get(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        headers=_auth(super_admin_jwt),
    ).json()
    assert body["provisioning"]["admin_invited"] == "TRUE"


async def test_ob4_patch_updates_resume_state(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    tenant = await make_tenant(name="OB4")
    cleanup_onboarding.append(tenant.id)
    patch = app_client.patch(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        json={"current_step": "billing",
              "section_status": {"legal": "done", "billing": "in_progress"}},
        headers=_auth(super_admin_jwt),
    )
    assert patch.status_code == 200, patch.text
    body = patch.json()
    assert body["current_step"] == "billing"
    assert body["section_status"] == {"legal": "done", "billing": "in_progress"}


async def test_ob5_patch_invalid_section_key_returns_422(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """LOAD-BEARING: invalid section_status key AND invalid current_step
    both 422 INVALID_SECTION_KEY naming the field."""
    tenant = await make_tenant(name="OB5")
    cleanup_onboarding.append(tenant.id)
    bad_key = app_client.patch(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        json={"section_status": {"not_a_section": "x"}},
        headers=_auth(super_admin_jwt),
    )
    assert bad_key.status_code == 422
    assert bad_key.json()["code"] == "INVALID_SECTION_KEY"
    assert "section_status" in bad_key.json()["message"]

    bad_step = app_client.patch(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        json={"current_step": "nope"},
        headers=_auth(super_admin_jwt),
    )
    assert bad_step.status_code == 422
    assert "current_step" in bad_step.json()["message"]


async def test_ob6_patch_tenant_jwt_denied_403(
    app_client, settings, make_tenant
) -> None:
    tenant = await make_tenant(name="OB6")
    resp = app_client.patch(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        json={"current_step": "review"},
        headers=_auth(_tenant_jwt(settings, tenant.id)),
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "PLATFORM_AUDIENCE_REQUIRED"


async def test_ob7_patch_emits_audit(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding,
    session_factory, platform_auth,
) -> None:
    tenant = await make_tenant(name="OB7")
    cleanup_onboarding.append(tenant.id)
    app_client.patch(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        json={"current_step": "company"},
        headers=_auth(super_admin_jwt),
    )
    actions = await _audit_actions(session_factory, platform_auth, tenant.id)
    assert actions == ["UPDATE_ONBOARDING:SUCCESS"]


# ===========================================================================
# complete-onboarding section gating (CO) -- Slice 2 item 6 + refinement 2
# ===========================================================================


async def test_co1_incomplete_sections_returns_409(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """LOAD-BEARING: complete-onboarding with no sections -> 409
    ONBOARDING_INCOMPLETE listing all missing."""
    tenant = await make_tenant(name="CO1", status=TenantStatus.ONBOARDING)
    cleanup_onboarding.append(tenant.id)
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/complete-onboarding",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "ONBOARDING_INCOMPLETE"


async def test_co2_missing_contact_still_409(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """legal + billing present but no contact -> still 409."""
    tenant = await make_tenant(name="CO2", status=TenantStatus.ONBOARDING)
    cleanup_onboarding.append(tenant.id)
    app_client.put(
        f"/api/v1/tenants/{tenant.id}/legal-profile",
        json=_LEGAL_BODY, headers=_auth(super_admin_jwt),
    )
    app_client.put(
        f"/api/v1/tenants/{tenant.id}/billing-profile",
        json=_BILLING_BODY, headers=_auth(super_admin_jwt),
    )
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/complete-onboarding",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "ONBOARDING_INCOMPLETE"


async def test_co3_all_gates_satisfied_completes(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """LOAD-BEARING (Slice 6): all six gates satisfied (legal + billing +
    contact + Auth0 org + invited admin + docs all-verified) -> 200 TRIAL."""
    tenant = await make_tenant(name="CO3", status=TenantStatus.ONBOARDING)
    cleanup_onboarding.append(tenant.id)
    await _seed_required_sections(app_client, super_admin_jwt, tenant.id)
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/complete-onboarding",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "TRIAL"


async def test_co4_non_onboarding_source_still_invalid_state(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """Existing ONBOARDING-source rule preserved: an ACTIVE tenant with
    all sections present is 409 INVALID_STATE_TRANSITION, not INCOMPLETE."""
    tenant = await make_tenant(name="CO4", status=TenantStatus.ACTIVE)
    cleanup_onboarding.append(tenant.id)
    await _seed_required_sections(app_client, super_admin_jwt, tenant.id)
    resp = app_client.post(
        f"/api/v1/tenants/{tenant.id}/complete-onboarding",
        headers=_auth(super_admin_jwt),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_STATE_TRANSITION"


async def test_co5_complete_emits_audit_success(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding,
    session_factory, platform_auth,
) -> None:
    tenant = await make_tenant(name="CO5", status=TenantStatus.ONBOARDING)
    cleanup_onboarding.append(tenant.id)
    await _seed_required_sections(app_client, super_admin_jwt, tenant.id)
    app_client.post(
        f"/api/v1/tenants/{tenant.id}/complete-onboarding",
        headers=_auth(super_admin_jwt),
    )
    actions = await _audit_actions(session_factory, platform_auth, tenant.id)
    assert "COMPLETE_ONBOARDING:SUCCESS" in actions


async def test_co6_incomplete_emits_conflict_audit(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding,
    session_factory, platform_auth,
) -> None:
    """LOAD-BEARING: a blocked completion emits a CONFLICT failure-path
    audit row for complete-onboarding."""
    tenant = await make_tenant(name="CO6", status=TenantStatus.ONBOARDING)
    cleanup_onboarding.append(tenant.id)
    app_client.post(
        f"/api/v1/tenants/{tenant.id}/complete-onboarding",
        headers=_auth(super_admin_jwt),
    )
    actions = await _audit_actions(session_factory, platform_auth, tenant.id)
    assert "COMPLETE_ONBOARDING:CONFLICT" in actions


async def test_co7_patch_after_complete_returns_409(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """LOAD-BEARING (refinement 2): PATCH onboarding is 409 once completed;
    section PUTs remain allowed."""
    tenant = await make_tenant(name="CO7", status=TenantStatus.ONBOARDING)
    cleanup_onboarding.append(tenant.id)
    # Provision the onboarding row + reach completion.
    app_client.patch(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        json={"current_step": "review"},
        headers=_auth(super_admin_jwt),
    )
    await _seed_required_sections(app_client, super_admin_jwt, tenant.id)
    done = app_client.post(
        f"/api/v1/tenants/{tenant.id}/complete-onboarding",
        headers=_auth(super_admin_jwt),
    )
    assert done.status_code == 200, done.text

    # PATCH now refused.
    patch = app_client.patch(
        f"/api/v1/tenants/{tenant.id}/onboarding",
        json={"current_step": "company"},
        headers=_auth(super_admin_jwt),
    )
    assert patch.status_code == 409
    assert patch.json()["code"] == "ONBOARDING_ALREADY_COMPLETED"

    # But a section PUT is still allowed (ongoing edit surface).
    still = app_client.put(
        f"/api/v1/tenants/{tenant.id}/billing-profile",
        json={**_BILLING_BODY, "currency": "USD"},
        headers=_auth(super_admin_jwt),
    )
    assert still.status_code == 200
    assert still.json()["currency"] == "USD"


async def _co_missing_fact_returns_409(
    app_client, jwt, tenant_id, *, auth0, invited, docs, missing_name,
) -> None:
    """Seed sections + all completion facts EXCEPT one, then assert
    complete-onboarding is 409 ONBOARDING_INCOMPLETE naming the omitted
    fact (Slice 6 gate: each added fact is individually required)."""
    await _seed_sections_only(app_client, jwt, tenant_id)
    await seed_completion_facts(
        app_client, tenant_id, auth0=auth0, invited=invited, docs=docs
    )
    resp = app_client.post(
        f"/api/v1/tenants/{tenant_id}/complete-onboarding",
        headers=_auth(jwt),
    )
    assert resp.status_code == 409, resp.text
    assert resp.json()["code"] == "ONBOARDING_INCOMPLETE"
    assert missing_name in resp.json()["message"]


async def test_co8_missing_auth0_org_returns_409(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """LOAD-BEARING (Slice 6): sections + admin + docs but no Auth0 org
    -> 409 naming auth0_organization."""
    tenant = await make_tenant(name="CO8", status=TenantStatus.ONBOARDING)
    cleanup_onboarding.append(tenant.id)
    await _co_missing_fact_returns_409(
        app_client, super_admin_jwt, tenant.id,
        auth0=False, invited=True, docs=True,
        missing_name="auth0_organization",
    )


async def test_co9_missing_admin_invited_returns_409(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """LOAD-BEARING (Slice 6): sections + Auth0 org + docs but no invited
    admin -> 409 naming admin_invited."""
    tenant = await make_tenant(name="CO9", status=TenantStatus.ONBOARDING)
    cleanup_onboarding.append(tenant.id)
    await _co_missing_fact_returns_409(
        app_client, super_admin_jwt, tenant.id,
        auth0=True, invited=False, docs=True,
        missing_name="admin_invited",
    )


async def test_co10_documents_not_all_verified_returns_409(
    app_client, super_admin_jwt, make_tenant, cleanup_onboarding
) -> None:
    """LOAD-BEARING (Slice 6): sections + Auth0 org + admin but no verified
    document -> 409 naming documents."""
    tenant = await make_tenant(name="CO10", status=TenantStatus.ONBOARDING)
    cleanup_onboarding.append(tenant.id)
    await _co_missing_fact_returns_409(
        app_client, super_admin_jwt, tenant.id,
        auth0=True, invited=True, docs=False,
        missing_name="documents",
    )
