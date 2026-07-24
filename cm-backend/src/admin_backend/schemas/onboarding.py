"""Pydantic schemas for the client-onboarding wizard (Slice 2).

Section resources (legal profile, tax registrations, billing profile,
contacts) plus the onboarding-state resource. Reads use
``from_attributes=True`` and hide audit-actor columns per the D-28
convention; requests use ``extra="forbid"``.

Lookups-coded fields (entity_type, registration_type, payment_terms,
currency, contact_type) are plain strings here; they are validated
app-side against the active ``core.lookups`` rows in ``OnboardingRepo``
(a Pydantic validator would raise the Pydantic 422 envelope, not the
project envelope). Section-key validation for the onboarding PATCH is
likewise app-side so the offending field is named in the project
envelope.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


# The fixed wizard-section vocabulary. current_step and every
# section_status key are validated against this set (Slice 2 item 4 +
# refinement 1). Ordered as the wizard presents them.
WIZARD_SECTION_KEYS: tuple[str, ...] = (
    "company",
    "legal",
    "billing",
    "contacts",
    "documents",
    "access",
    "review",
)


# ---------------------------------------------------------------------------
# Legal profile (1:1)
# ---------------------------------------------------------------------------


class LegalProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    legal_entity_name: str
    entity_type: str
    registration_number: str | None
    incorporation_date: date | None
    registered_address: str | None


class LegalProfileUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal_entity_name: str = Field(min_length=1, max_length=200)
    entity_type: str = Field(min_length=1)
    registration_number: str | None = None
    incorporation_date: date | None = None
    registered_address: str | None = None


# ---------------------------------------------------------------------------
# Tax registrations (1:N)
# ---------------------------------------------------------------------------


class TaxRegistrationItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    registration_type: str
    registration_number: str
    jurisdiction: str | None


class TaxRegistrationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    registration_type: str = Field(min_length=1)
    registration_number: str = Field(min_length=1)
    jurisdiction: str | None = None


class TaxRegistrationsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[TaxRegistrationItem]


class TaxRegistrationsReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Empty list is allowed: it clears the tenant's registrations.
    items: list[TaxRegistrationInput]


# ---------------------------------------------------------------------------
# Billing profile (1:1)
# ---------------------------------------------------------------------------


class BillingProfileRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    payment_terms: str | None
    currency: str | None
    billing_email: str | None
    billing_contact_name: str | None
    billing_address: str | None


class BillingProfileUpsertRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    payment_terms: str | None = None
    currency: str | None = None
    billing_email: EmailStr | None = None
    billing_contact_name: str | None = None
    billing_address: str | None = None

    @field_validator("billing_email")
    @classmethod
    def _lowercase_email(cls, v: str | None) -> str | None:
        # DDL ck_tenant_billing_profile_email_lowercase requires the
        # stored value equal lower(value).
        return v.lower() if v is not None else None


# ---------------------------------------------------------------------------
# Contacts (1:N)
# ---------------------------------------------------------------------------


class ContactItem(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    contact_type: str
    name: str
    email: str | None
    phone: str | None


class ContactInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    contact_type: str = Field(min_length=1)
    name: str = Field(min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = None

    @field_validator("email")
    @classmethod
    def _lowercase_email(cls, v: str | None) -> str | None:
        return v.lower() if v is not None else None


class ContactsRead(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ContactItem]


class ContactsReplaceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    items: list[ContactInput]


# ---------------------------------------------------------------------------
# Onboarding state resource
# ---------------------------------------------------------------------------


# Derived provisioning-check status. UNKNOWN when the fact is not
# derivable from cm-backend's own schema (auth0_organization: there is
# no per-tenant Auth0 org id column anywhere; verified against code).
ProvisioningStatus = Literal["TRUE", "FALSE", "UNKNOWN"]


class OnboardingSectionsPresent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    legal: bool
    tax: bool
    billing: bool
    contacts: bool
    documents: bool


class OnboardingProvisioning(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Not derivable from the current schema -> always UNKNOWN in Slice 2.
    auth0_organization: ProvisioningStatus
    # Derived live from tenant_users.invited_at IS NOT NULL.
    admin_invited: ProvisioningStatus


class OnboardingStateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    current_step: str | None
    section_status: dict[str, Any]
    completed_at: datetime | None
    completed_by_user_id: UUID | None
    sections_present: OnboardingSectionsPresent
    provisioning: OnboardingProvisioning


class OnboardingPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # Both optional; keys validated app-side against WIZARD_SECTION_KEYS
    # so the project error envelope names the offending field.
    current_step: str | None = None
    section_status: dict[str, Any] | None = None
