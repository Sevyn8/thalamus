"""Client-onboarding wizard section + state endpoints.

All routes are tenant-scoped under ``/tenants/{tenant_id}`` and gated
``ADMIN.TENANTS.CONFIGURE.GLOBAL`` with ``audience="PLATFORM"`` (staff
onboarding, D-12). Section reads/writes and the onboarding-state
resource live here; ``complete-onboarding`` stays on the tenants router
(it is a tenant lifecycle transition).

Sits behind the same ``/tenants`` prefix as ``tenants_router``; FastAPI
composes both routers under that prefix without conflict (distinct
paths).
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession

from admin_backend.auth.context import AuthContext
from admin_backend.auth.permissions import require
from admin_backend.dependencies import (
    get_auth_context,
    get_tenant_session_dep,
)
from admin_backend.errors import (
    OnboardingSectionNotFoundError,
    TenantNotFoundError,
)
from admin_backend.models.permission import (
    PermissionAction,
    PermissionResource,
    PermissionScope,
)
from admin_backend.models.tenant_module_access import ModuleCode
from admin_backend.repositories.onboarding import OnboardingRepo
from admin_backend.schemas.onboarding import (
    BillingProfileRead,
    BillingProfileUpsertRequest,
    ContactItem,
    ContactsRead,
    ContactsReplaceRequest,
    LegalProfileRead,
    LegalProfileUpsertRequest,
    OnboardingPatchRequest,
    OnboardingStateResponse,
    TaxRegistrationItem,
    TaxRegistrationsRead,
    TaxRegistrationsReplaceRequest,
)


router = APIRouter(prefix="/tenants", tags=["onboarding"])

_repo = OnboardingRepo()


def _gate() -> Any:
    """One gate for every onboarding section/state route:
    ``ADMIN.TENANTS.CONFIGURE.GLOBAL``, PLATFORM audience."""
    return require(
        ModuleCode.ADMIN,
        PermissionResource.TENANTS,
        PermissionAction.CONFIGURE,
        PermissionScope.GLOBAL,
        audience="PLATFORM",
    )


async def _require_tenant_visible(
    repo: OnboardingRepo, session: AsyncSession, tenant_id: UUID
) -> None:
    if await repo.tenant_name_or_none(session, tenant_id) is None:
        raise TenantNotFoundError(
            f"Tenant {tenant_id} not visible to this session",
            tenant_id=str(tenant_id),
        )


# ---------------------------------------------------------------------------
# Legal profile (1:1)
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}/legal-profile", response_model=LegalProfileRead
)
async def get_legal_profile(
    tenant_id: UUID,
    _: None = Depends(_gate()),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    await _require_tenant_visible(_repo, session, tenant_id)
    row = await _repo.get_legal_profile(session, tenant_id)
    if row is None:
        raise OnboardingSectionNotFoundError(section="Legal profile")
    return LegalProfileRead.model_validate(row)


@router.put(
    "/{tenant_id}/legal-profile", response_model=LegalProfileRead
)
async def put_legal_profile(
    tenant_id: UUID,
    body: LegalProfileUpsertRequest,
    request: Request,
    _: None = Depends(_gate()),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    row = await _repo.upsert_legal_profile(
        session,
        tenant_id,
        legal_entity_name=body.legal_entity_name,
        entity_type=body.entity_type,
        registration_number=body.registration_number,
        incorporation_date=body.incorporation_date,
        registered_address=body.registered_address,
        actor_user_id=auth.user_id,
        auth=auth,
        request_id=request.state.request_id,
    )
    return LegalProfileRead.model_validate(row)


# ---------------------------------------------------------------------------
# Tax registrations (1:N)
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}/tax-registrations", response_model=TaxRegistrationsRead
)
async def get_tax_registrations(
    tenant_id: UUID,
    _: None = Depends(_gate()),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    await _require_tenant_visible(_repo, session, tenant_id)
    rows = await _repo.list_tax_registrations(session, tenant_id)
    return TaxRegistrationsRead(
        items=[TaxRegistrationItem.model_validate(r) for r in rows]
    )


@router.put(
    "/{tenant_id}/tax-registrations", response_model=TaxRegistrationsRead
)
async def put_tax_registrations(
    tenant_id: UUID,
    body: TaxRegistrationsReplaceRequest,
    request: Request,
    _: None = Depends(_gate()),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    rows = await _repo.replace_tax_registrations(
        session,
        tenant_id,
        items=[it.model_dump() for it in body.items],
        actor_user_id=auth.user_id,
        auth=auth,
        request_id=request.state.request_id,
    )
    return TaxRegistrationsRead(
        items=[TaxRegistrationItem.model_validate(r) for r in rows]
    )


# ---------------------------------------------------------------------------
# Billing profile (1:1)
# ---------------------------------------------------------------------------


@router.get(
    "/{tenant_id}/billing-profile", response_model=BillingProfileRead
)
async def get_billing_profile(
    tenant_id: UUID,
    _: None = Depends(_gate()),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    await _require_tenant_visible(_repo, session, tenant_id)
    row = await _repo.get_billing_profile(session, tenant_id)
    if row is None:
        raise OnboardingSectionNotFoundError(section="Billing profile")
    return BillingProfileRead.model_validate(row)


@router.put(
    "/{tenant_id}/billing-profile", response_model=BillingProfileRead
)
async def put_billing_profile(
    tenant_id: UUID,
    body: BillingProfileUpsertRequest,
    request: Request,
    _: None = Depends(_gate()),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    row = await _repo.upsert_billing_profile(
        session,
        tenant_id,
        payment_terms=body.payment_terms,
        currency=body.currency,
        billing_email=body.billing_email,
        billing_contact_name=body.billing_contact_name,
        billing_address=body.billing_address,
        actor_user_id=auth.user_id,
        auth=auth,
        request_id=request.state.request_id,
    )
    return BillingProfileRead.model_validate(row)


# ---------------------------------------------------------------------------
# Contacts (1:N)
# ---------------------------------------------------------------------------


@router.get("/{tenant_id}/contacts", response_model=ContactsRead)
async def get_contacts(
    tenant_id: UUID,
    _: None = Depends(_gate()),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    await _require_tenant_visible(_repo, session, tenant_id)
    rows = await _repo.list_contacts(session, tenant_id)
    return ContactsRead(items=[ContactItem.model_validate(r) for r in rows])


@router.put("/{tenant_id}/contacts", response_model=ContactsRead)
async def put_contacts(
    tenant_id: UUID,
    body: ContactsReplaceRequest,
    request: Request,
    _: None = Depends(_gate()),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    rows = await _repo.replace_contacts(
        session,
        tenant_id,
        items=[it.model_dump() for it in body.items],
        actor_user_id=auth.user_id,
        auth=auth,
        request_id=request.state.request_id,
    )
    return ContactsRead(items=[ContactItem.model_validate(r) for r in rows])


# ---------------------------------------------------------------------------
# Onboarding state resource
# ---------------------------------------------------------------------------


@router.get("/{tenant_id}/onboarding", response_model=OnboardingStateResponse)
async def get_onboarding(
    tenant_id: UUID,
    _: None = Depends(_gate()),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    state = await _repo.get_onboarding_state(session, tenant_id)
    if state is None:
        raise TenantNotFoundError(
            f"Tenant {tenant_id} not visible to this session",
            tenant_id=str(tenant_id),
        )
    return OnboardingStateResponse.model_validate(state)


@router.patch(
    "/{tenant_id}/onboarding", response_model=OnboardingStateResponse
)
async def patch_onboarding(
    tenant_id: UUID,
    body: OnboardingPatchRequest,
    request: Request,
    _: None = Depends(_gate()),
    auth: AuthContext = Depends(get_auth_context),
    session: AsyncSession = Depends(get_tenant_session_dep),
) -> Any:
    sent = body.model_dump(exclude_unset=True)
    state = await _repo.patch_onboarding(
        session,
        tenant_id,
        current_step=body.current_step,
        current_step_set="current_step" in sent,
        section_status=body.section_status,
        section_status_set="section_status" in sent,
        actor_user_id=auth.user_id,
        auth=auth,
        request_id=request.state.request_id,
    )
    return OnboardingStateResponse.model_validate(state)
