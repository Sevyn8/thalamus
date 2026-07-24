# Client Onboarding endpoints (Slice 2)

Wizard section resources + onboarding-state, all tenant-scoped under
`/api/v1/tenants/{tenant_id}`. Every endpoint is gated
`ADMIN.TENANTS.CONFIGURE.GLOBAL` with `audience="PLATFORM"` (staff-driven
onboarding, D-12). `complete-onboarding` lives on the tenants router (it is
a tenant lifecycle transition) and gains section gating in this slice.

The machine-readable contract is the OpenAPI spec at
`/api/v1/openapi.json` (regeneration is a tracked follow-up); this file is
the human-readable companion.

## Auth / gate

- Auth: `Authorization: Bearer <jwt>`.
- Gate: `ADMIN.TENANTS.CONFIGURE.GLOBAL`, `audience="PLATFORM"`. A TENANT
  JWT is rejected 403 `PLATFORM_AUDIENCE_REQUIRED` (Layer 1, before any DB
  read). A PLATFORM caller lacking the grant is 403 `PERMISSION_DENIED`.
- Cross-tenant / missing tenant: 404 `TENANT_NOT_FOUND` (RLS-as-404, D-17).

## Sections

### Legal profile (1:1)
- `GET /{tenant_id}/legal-profile` -> `LegalProfileRead`; 404
  `SECTION_NOT_FOUND` if not yet saved (tenant exists), 404
  `TENANT_NOT_FOUND` if the tenant is not visible.
- `PUT /{tenant_id}/legal-profile` -> upsert (1:1), returns
  `LegalProfileRead`. Body: `legal_entity_name` (required), `entity_type`
  (required, lookups `entity_type`), `registration_number?`,
  `incorporation_date?`, `registered_address?`.

### Tax registrations (1:N)
- `GET /{tenant_id}/tax-registrations` -> `{items: [...]}` (empty list if
  none).
- `PUT /{tenant_id}/tax-registrations` -> transactional full-replace of the
  tenant's set. Body: `{items: [{registration_type (lookups
  tax_registration_type), registration_number, jurisdiction?}]}`. Multi-state
  GSTIN supported (uniqueness is `(type, number)`). In-payload duplicate
  `(type, number)` -> 422 `DUPLICATE_SECTION_ROW` before any write. PAN/GSTIN
  length enforced by the DDL CHECK.

### Billing profile (1:1)
- `GET /{tenant_id}/billing-profile` -> `BillingProfileRead`; 404
  `SECTION_NOT_FOUND` if unsaved.
- `PUT /{tenant_id}/billing-profile` -> upsert. Body: `payment_terms?`
  (lookups `payment_terms`), `currency?` (lookups `currency`),
  `billing_email?`, `billing_contact_name?`, `billing_address?`.

### Contacts (1:N)
- `GET /{tenant_id}/contacts` -> `{items: [...]}`.
- `PUT /{tenant_id}/contacts` -> transactional full-replace. Body:
  `{items: [{contact_type (lookups contact_type), name, email?, phone?}]}`.
  In-payload exact-duplicate rows -> 422 `DUPLICATE_SECTION_ROW`.

### Validation (all sections)
Lookups-coded fields (`entity_type`, `registration_type`, `payment_terms`,
`currency`, `contact_type`) are validated against ACTIVE `core.lookups` rows
before any write; an invalid value -> 422 `INVALID_LOOKUP_CODE` naming the
field.

## Onboarding state

### `GET /{tenant_id}/onboarding` -> `OnboardingStateResponse`
```
{
  "current_step": null,
  "section_status": {},
  "completed_at": null,
  "completed_by_user_id": null,
  "sections_present": {"legal": false, "tax": false, "billing": false,
                        "contacts": false, "documents": false},
  "provisioning": {"auth0_organization": "UNKNOWN", "admin_invited": "FALSE"}
}
```
- `sections_present.*` are live presence flags (a row exists in the section
  table).
- `provisioning.admin_invited` is derived live from
  `tenant_users.invited_at IS NOT NULL` -> `"TRUE"`/`"FALSE"`.
- `provisioning.auth0_organization` is always `"UNKNOWN"`: no per-tenant
  Auth0 organization id is stored anywhere in cm-backend's schema (verified
  against code, not docs). Not a proxy; a genuine "not derivable".

### `PATCH /{tenant_id}/onboarding` -> `OnboardingStateResponse`
Updates the wizard resume-state. Body: `current_step?`, `section_status?`.
`current_step` and every `section_status` key are validated against the
fixed set `{company, legal, billing, contacts, documents, access, review}`;
an invalid key -> 422 `INVALID_SECTION_KEY` naming the field. Once
`completed_at` is set, PATCH is refused 409 `ONBOARDING_ALREADY_COMPLETED`
(the resume-state is frozen after completion). Section PUTs remain allowed
after completion (the ongoing edit surface).

## complete-onboarding gating (tenants router)

`POST /{tenant_id}/complete-onboarding` (ONBOARDING -> TRIAL) additionally
requires, in this slice: a legal profile, a billing profile, and at least
one contact. If any is missing -> 409 `ONBOARDING_INCOMPLETE` listing the
missing sections. The existing ONBOARDING-source rule is preserved
(non-ONBOARDING source -> 409 `INVALID_STATE_TRANSITION`). Document
completeness is intentionally NOT gated here (documents are Slice 3).

## Audit

Every write route emits exactly one audit event (success path), and the
1:N full-replace PUTs emit one event per request, not per row. Failure
outcomes (e.g., the `ONBOARDING_INCOMPLETE` 409) emit a failure-path row.
Action codes: `UPSERT_LEGAL_PROFILE`, `REPLACE_TAX_REGISTRATIONS`,
`UPSERT_BILLING_PROFILE`, `REPLACE_CONTACTS`, `UPDATE_ONBOARDING`,
`COMPLETE_ONBOARDING`; all `resource_type=TENANT`, routed to
`tenant_activity_audit_logs`.

## Implementation reference
- Router: `src/admin_backend/routers/v1/onboarding.py` (sections + state);
  `src/admin_backend/routers/v1/tenants.py` (complete-onboarding).
- Repo: `src/admin_backend/repositories/onboarding.py`;
  `TenantsRepo.complete_onboarding` (section gating + audit).
- Schemas: `src/admin_backend/schemas/onboarding.py`.
- Errors: `INVALID_LOOKUP_CODE`, `INVALID_SECTION_KEY`,
  `DUPLICATE_SECTION_ROW`, `SECTION_NOT_FOUND`, `ONBOARDING_INCOMPLETE`,
  `ONBOARDING_ALREADY_COMPLETED` in `src/admin_backend/errors.py`.
- Audit wiring: `AUDITED_ROUTES` + `_ACTION_LABELS` in
  `src/admin_backend/audit/emit.py`.
