"""Data access for the client-onboarding wizard sections + state.

One ``OnboardingRepo`` covering the four section resources (legal
profile 1:1, tax registrations 1:N, billing profile 1:1, contacts 1:N)
plus the onboarding-state resource. Raw ``text()`` SQL, every identifier
schema-qualified via ``get_settings().db_schema`` per CSD-03; RLS-bound
through the session GUCs (PLATFORM callers see all rows via the D-29
OR-branch; the endpoints are PLATFORM-audience-gated anyway).

Write methods (upserts + full-replaces) emit exactly one audit event
per call via ``emit_audit_event``. The 1:N replaces run
DELETE + INSERT in the request transaction and emit a single event, not
one per row (guardrail). ``auth`` + ``request_id`` are optional and
both-or-neither: repo-level tests may omit them to skip emission.

Lookups-coded fields are validated against the ACTIVE ``core.lookups``
rows; an invalid code raises ``InvalidLookupCodeError`` (422) naming the
field, before any DB write.
"""
from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy import Row, text
from sqlalchemy.ext.asyncio import AsyncSession

from admin_backend.auth.context import AuthContext
from admin_backend.audit.emit import (
    build_success_details_for_create,
    emit_audit_event,
)
from admin_backend.config import get_settings
from admin_backend.errors import (
    DuplicateSectionRowError,
    InvalidLookupCodeError,
    InvalidSectionKeyError,
    OnboardingAlreadyCompletedError,
    OnboardingSectionNotFoundError,
    TenantNotFoundError,
)
from admin_backend.models import AuditResultType
from admin_backend.repositories.lookups import LookupsRepo
from admin_backend.schemas.onboarding import WIZARD_SECTION_KEYS


_lookups_repo = LookupsRepo()


def _emit_args_valid(
    auth: AuthContext | None, request_id: UUID | None
) -> bool:
    if (auth is None) != (request_id is None):
        raise ValueError(
            "auth and request_id must be provided together for audit "
            "emission, or both omitted"
        )
    return auth is not None and request_id is not None


class OnboardingRepo:
    """Read + write access for onboarding sections and wizard state."""

    # ------------------------------------------------------------------
    # Tenant visibility + lookup-code validation
    # ------------------------------------------------------------------

    async def tenant_name_or_none(
        self, session: AsyncSession, tenant_id: UUID
    ) -> str | None:
        """Return the tenant's name if visible to this session, else None
        (missing or RLS-filtered -> the router raises 404 per D-17)."""
        schema = get_settings().db_schema
        result = await session.execute(
            text(f"SELECT name FROM {schema}.tenants WHERE id = :tid"),
            {"tid": tenant_id},
        )
        row = result.first()
        return str(row.name) if row is not None else None

    async def _require_tenant(
        self, session: AsyncSession, tenant_id: UUID
    ) -> str:
        name = await self.tenant_name_or_none(session, tenant_id)
        if name is None:
            raise TenantNotFoundError(
                f"Tenant {tenant_id} not visible to this session",
                tenant_id=str(tenant_id),
            )
        return name

    async def _validate_codes(
        self,
        session: AsyncSession,
        checks: list[tuple[str, str | None, str]],
    ) -> None:
        """Validate (field, value, list_name) triples against ACTIVE
        lookups. None values skip (nullable columns). Raises
        ``InvalidLookupCodeError`` on the first invalid code."""
        needed = sorted({ln for _f, v, ln in checks if v is not None})
        if not needed:
            return
        active = await _lookups_repo.get_lists_batch(session, needed)
        active_codes: dict[str, set[str]] = {
            ln: {row.code for row in rows} for ln, rows in active.items()
        }
        for field, value, list_name in checks:
            if value is None:
                continue
            if value not in active_codes.get(list_name, set()):
                raise InvalidLookupCodeError(
                    field=field, value=value, list_name=list_name
                )

    # ------------------------------------------------------------------
    # Legal profile (1:1)
    # ------------------------------------------------------------------

    async def get_legal_profile(
        self, session: AsyncSession, tenant_id: UUID
    ) -> Row[Any] | None:
        schema = get_settings().db_schema
        result = await session.execute(
            text(
                f"""
                SELECT legal_entity_name, entity_type, registration_number,
                       incorporation_date, registered_address
                FROM {schema}.tenant_legal_profile
                WHERE tenant_id = :tid
                """
            ),
            {"tid": tenant_id},
        )
        return result.first()

    async def upsert_legal_profile(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        legal_entity_name: str,
        entity_type: str,
        registration_number: str | None,
        incorporation_date: Any,
        registered_address: str | None,
        actor_user_id: UUID,
        auth: AuthContext | None = None,
        request_id: UUID | None = None,
    ) -> Row[Any]:
        schema = get_settings().db_schema
        tenant_name = await self._require_tenant(session, tenant_id)
        await self._validate_codes(
            session, [("entity_type", entity_type, "entity_type")]
        )

        result = await session.execute(
            text(
                f"""
                INSERT INTO {schema}.tenant_legal_profile (
                    tenant_id, legal_entity_name, entity_type,
                    registration_number, incorporation_date,
                    registered_address, created_by_user_id, updated_by_user_id
                ) VALUES (
                    :tid, :name, :etype, :regnum, :incdate, :addr,
                    :actor, :actor
                )
                ON CONFLICT (tenant_id) DO UPDATE SET
                    legal_entity_name = EXCLUDED.legal_entity_name,
                    entity_type = EXCLUDED.entity_type,
                    registration_number = EXCLUDED.registration_number,
                    incorporation_date = EXCLUDED.incorporation_date,
                    registered_address = EXCLUDED.registered_address,
                    updated_by_user_id = :actor,
                    updated_at = now()
                RETURNING legal_entity_name, entity_type, registration_number,
                          incorporation_date, registered_address
                """
            ),
            {
                "tid": tenant_id,
                "name": legal_entity_name,
                "etype": entity_type,
                "regnum": registration_number,
                "incdate": incorporation_date,
                "addr": registered_address,
                "actor": actor_user_id,
            },
        )
        row = result.first()
        assert row is not None  # RETURNING always yields a row
        await self._emit(
            session,
            auth=auth,
            request_id=request_id,
            action="UPSERT_LEGAL_PROFILE",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            snapshot={"section": "legal_profile", "entity_type": entity_type},
        )
        return row

    # ------------------------------------------------------------------
    # Tax registrations (1:N; full-replace)
    # ------------------------------------------------------------------

    async def list_tax_registrations(
        self, session: AsyncSession, tenant_id: UUID
    ) -> list[Row[Any]]:
        schema = get_settings().db_schema
        result = await session.execute(
            text(
                f"""
                SELECT registration_type, registration_number, jurisdiction
                FROM {schema}.tenant_tax_registrations
                WHERE tenant_id = :tid
                ORDER BY registration_type, registration_number
                """
            ),
            {"tid": tenant_id},
        )
        return list(result.all())

    async def replace_tax_registrations(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        items: list[dict[str, Any]],
        actor_user_id: UUID,
        auth: AuthContext | None = None,
        request_id: UUID | None = None,
    ) -> list[Row[Any]]:
        schema = get_settings().db_schema
        tenant_name = await self._require_tenant(session, tenant_id)

        # Validate codes (each row's registration_type).
        await self._validate_codes(
            session,
            [
                ("registration_type", it["registration_type"], "tax_registration_type")
                for it in items
            ],
        )
        # App-side in-payload duplicate (type, number) check (refinement 3),
        # before any DB write. Honours uq_tenant_tax_registrations_tenant_type_number.
        seen: set[tuple[str, str]] = set()
        for it in items:
            key = (it["registration_type"], it["registration_number"])
            if key in seen:
                raise DuplicateSectionRowError(
                    field="tax_registrations",
                    value=f"{key[0]} / {key[1]}",
                )
            seen.add(key)

        # Transactional full-replace: delete all, insert the new set.
        await session.execute(
            text(
                f"DELETE FROM {schema}.tenant_tax_registrations "
                "WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
        for it in items:
            await session.execute(
                text(
                    f"""
                    INSERT INTO {schema}.tenant_tax_registrations (
                        tenant_id, registration_type, registration_number,
                        jurisdiction, created_by_user_id, updated_by_user_id
                    ) VALUES (
                        :tid, :rtype, :rnum, :juris, :actor, :actor
                    )
                    """
                ),
                {
                    "tid": tenant_id,
                    "rtype": it["registration_type"],
                    "rnum": it["registration_number"],
                    "juris": it.get("jurisdiction"),
                    "actor": actor_user_id,
                },
            )
        await self._emit(
            session,
            auth=auth,
            request_id=request_id,
            action="REPLACE_TAX_REGISTRATIONS",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            snapshot={"section": "tax_registrations", "count": len(items)},
        )
        return await self.list_tax_registrations(session, tenant_id)

    # ------------------------------------------------------------------
    # Billing profile (1:1)
    # ------------------------------------------------------------------

    async def get_billing_profile(
        self, session: AsyncSession, tenant_id: UUID
    ) -> Row[Any] | None:
        schema = get_settings().db_schema
        result = await session.execute(
            text(
                f"""
                SELECT payment_terms, currency, billing_email,
                       billing_contact_name, billing_address
                FROM {schema}.tenant_billing_profile
                WHERE tenant_id = :tid
                """
            ),
            {"tid": tenant_id},
        )
        return result.first()

    async def upsert_billing_profile(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        payment_terms: str | None,
        currency: str | None,
        billing_email: str | None,
        billing_contact_name: str | None,
        billing_address: str | None,
        actor_user_id: UUID,
        auth: AuthContext | None = None,
        request_id: UUID | None = None,
    ) -> Row[Any]:
        schema = get_settings().db_schema
        tenant_name = await self._require_tenant(session, tenant_id)
        await self._validate_codes(
            session,
            [
                ("payment_terms", payment_terms, "payment_terms"),
                ("currency", currency, "currency"),
            ],
        )

        result = await session.execute(
            text(
                f"""
                INSERT INTO {schema}.tenant_billing_profile (
                    tenant_id, payment_terms, currency, billing_email,
                    billing_contact_name, billing_address,
                    created_by_user_id, updated_by_user_id
                ) VALUES (
                    :tid, :terms, :curr, :email, :cname, :addr, :actor, :actor
                )
                ON CONFLICT (tenant_id) DO UPDATE SET
                    payment_terms = EXCLUDED.payment_terms,
                    currency = EXCLUDED.currency,
                    billing_email = EXCLUDED.billing_email,
                    billing_contact_name = EXCLUDED.billing_contact_name,
                    billing_address = EXCLUDED.billing_address,
                    updated_by_user_id = :actor,
                    updated_at = now()
                RETURNING payment_terms, currency, billing_email,
                          billing_contact_name, billing_address
                """
            ),
            {
                "tid": tenant_id,
                "terms": payment_terms,
                "curr": currency,
                "email": billing_email,
                "cname": billing_contact_name,
                "addr": billing_address,
                "actor": actor_user_id,
            },
        )
        row = result.first()
        assert row is not None
        await self._emit(
            session,
            auth=auth,
            request_id=request_id,
            action="UPSERT_BILLING_PROFILE",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            snapshot={"section": "billing_profile"},
        )
        return row

    # ------------------------------------------------------------------
    # Contacts (1:N; full-replace)
    # ------------------------------------------------------------------

    async def list_contacts(
        self, session: AsyncSession, tenant_id: UUID
    ) -> list[Row[Any]]:
        schema = get_settings().db_schema
        result = await session.execute(
            text(
                f"""
                SELECT contact_type, name, email, phone
                FROM {schema}.tenant_contacts
                WHERE tenant_id = :tid
                ORDER BY contact_type, name
                """
            ),
            {"tid": tenant_id},
        )
        return list(result.all())

    async def replace_contacts(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        items: list[dict[str, Any]],
        actor_user_id: UUID,
        auth: AuthContext | None = None,
        request_id: UUID | None = None,
    ) -> list[Row[Any]]:
        schema = get_settings().db_schema
        tenant_name = await self._require_tenant(session, tenant_id)
        await self._validate_codes(
            session,
            [
                ("contact_type", it["contact_type"], "contact_type")
                for it in items
            ],
        )
        # In-payload exact-duplicate contact rows -> 422 (refinement 3).
        # The DDL does not enforce contact uniqueness, so guard app-side.
        seen: set[tuple[str, str, str | None, str | None]] = set()
        for it in items:
            key = (
                it["contact_type"],
                it["name"],
                it.get("email"),
                it.get("phone"),
            )
            if key in seen:
                raise DuplicateSectionRowError(
                    field="contacts",
                    value=f"{it['contact_type']} / {it['name']}",
                )
            seen.add(key)

        await session.execute(
            text(
                f"DELETE FROM {schema}.tenant_contacts WHERE tenant_id = :tid"
            ),
            {"tid": tenant_id},
        )
        for it in items:
            await session.execute(
                text(
                    f"""
                    INSERT INTO {schema}.tenant_contacts (
                        tenant_id, contact_type, name, email, phone,
                        created_by_user_id, updated_by_user_id
                    ) VALUES (
                        :tid, :ctype, :name, :email, :phone, :actor, :actor
                    )
                    """
                ),
                {
                    "tid": tenant_id,
                    "ctype": it["contact_type"],
                    "name": it["name"],
                    "email": it.get("email"),
                    "phone": it.get("phone"),
                    "actor": actor_user_id,
                },
            )
        await self._emit(
            session,
            auth=auth,
            request_id=request_id,
            action="REPLACE_CONTACTS",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            snapshot={"section": "contacts", "count": len(items)},
        )
        return await self.list_contacts(session, tenant_id)

    # ------------------------------------------------------------------
    # Onboarding state resource
    # ------------------------------------------------------------------

    async def get_onboarding_state(
        self, session: AsyncSession, tenant_id: UUID
    ) -> dict[str, Any] | None:
        """Return the wizard state dict, or None if the tenant is not
        visible. The tenant_onboarding row may be absent (seed tenants
        predate onboarding-row provisioning); defaults are synthesised."""
        schema = get_settings().db_schema
        if await self.tenant_name_or_none(session, tenant_id) is None:
            return None

        ob = (
            await session.execute(
                text(
                    f"""
                    SELECT current_step, section_status, completed_at,
                           completed_by_user_id
                    FROM {schema}.tenant_onboarding
                    WHERE tenant_id = :tid
                    """
                ),
                {"tid": tenant_id},
            )
        ).first()

        presence = (
            await session.execute(
                text(
                    f"""
                    SELECT
                      EXISTS(SELECT 1 FROM {schema}.tenant_legal_profile
                             WHERE tenant_id = :tid) AS legal,
                      EXISTS(SELECT 1 FROM {schema}.tenant_tax_registrations
                             WHERE tenant_id = :tid) AS tax,
                      EXISTS(SELECT 1 FROM {schema}.tenant_billing_profile
                             WHERE tenant_id = :tid) AS billing,
                      EXISTS(SELECT 1 FROM {schema}.tenant_contacts
                             WHERE tenant_id = :tid) AS contacts,
                      EXISTS(SELECT 1 FROM {schema}.tenant_users
                             WHERE tenant_id = :tid
                               AND invited_at IS NOT NULL) AS admin_invited,
                      EXISTS(SELECT 1 FROM {schema}.tenants
                             WHERE id = :tid
                               AND auth0_org_id IS NOT NULL) AS auth0_org
                    """
                ),
                {"tid": tenant_id},
            )
        ).one()

        # Documents section is a verification-status counts block.
        doc_counts = (
            await session.execute(
                text(
                    f"""
                    SELECT
                      COUNT(*) AS total,
                      COUNT(*) FILTER (
                        WHERE verification_status = 'PENDING_REVIEW'
                      ) AS pending_review,
                      COUNT(*) FILTER (
                        WHERE verification_status = 'VERIFIED'
                      ) AS verified,
                      COUNT(*) FILTER (
                        WHERE verification_status = 'REJECTED'
                      ) AS rejected
                    FROM {schema}.tenant_documents
                    WHERE tenant_id = :tid
                    """
                ),
                {"tid": tenant_id},
            )
        ).one()
        documents_block = {
            "total": int(doc_counts.total),
            "pending_review": int(doc_counts.pending_review),
            "verified": int(doc_counts.verified),
            "rejected": int(doc_counts.rejected),
            # all_verified: >=1 document AND none pending or rejected.
            "all_verified": (
                int(doc_counts.total) >= 1
                and int(doc_counts.pending_review) == 0
                and int(doc_counts.rejected) == 0
            ),
        }

        return {
            "current_step": ob.current_step if ob is not None else None,
            "section_status": (
                ob.section_status if ob is not None else {}
            ),
            "completed_at": ob.completed_at if ob is not None else None,
            "completed_by_user_id": (
                ob.completed_by_user_id if ob is not None else None
            ),
            "sections_present": {
                "legal": bool(presence.legal),
                "tax": bool(presence.tax),
                "billing": bool(presence.billing),
                "contacts": bool(presence.contacts),
                "documents": documents_block,
            },
            "provisioning": {
                # Derived from tenants.auth0_org_id,
                # stamped by POST /tenants/{id}/provision-auth0. TRUE once
                # the Auth0 Organization has been provisioned (and its id
                # persisted), FALSE otherwise. No longer UNKNOWN: the fact
                # is a durable DB column, so the review gate reads it without
                # touching Auth0. Pre-existing Auth0 orgs read FALSE until
                # the idempotent provision endpoint is re-run.
                "auth0_organization": "TRUE" if presence.auth0_org else "FALSE",
                "admin_invited": "TRUE" if presence.admin_invited else "FALSE",
            },
        }

    async def patch_onboarding(
        self,
        session: AsyncSession,
        tenant_id: UUID,
        *,
        current_step: str | None,
        current_step_set: bool,
        section_status: dict[str, Any] | None,
        section_status_set: bool,
        actor_user_id: UUID,
        auth: AuthContext | None = None,
        request_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Update the wizard resume-state. Validates section keys against
        WIZARD_SECTION_KEYS; refuses (409) once completed_at is set
        (refinement 2). Upserts the tenant_onboarding row so seed tenants
        without a provisioned row are handled."""
        schema = get_settings().db_schema
        tenant_name = await self._require_tenant(session, tenant_id)

        # Section-key validation (current_step + section_status keys).
        if current_step_set and current_step is not None:
            if current_step not in WIZARD_SECTION_KEYS:
                raise InvalidSectionKeyError(
                    field="current_step", invalid=[current_step]
                )
        if section_status_set and section_status is not None:
            bad = [k for k in section_status if k not in WIZARD_SECTION_KEYS]
            if bad:
                raise InvalidSectionKeyError(
                    field="section_status", invalid=sorted(bad)
                )

        # Refuse resume-state edits once onboarding is complete.
        existing = (
            await session.execute(
                text(
                    f"SELECT completed_at FROM {schema}.tenant_onboarding "
                    "WHERE tenant_id = :tid"
                ),
                {"tid": tenant_id},
            )
        ).first()
        if existing is not None and existing.completed_at is not None:
            raise OnboardingAlreadyCompletedError(
                f"onboarding already complete for tenant {tenant_id}; "
                "resume state is frozen",
                tenant_id=str(tenant_id),
            )

        # Build the upsert. Only provided fields are written; on INSERT
        # the omitted field takes its DDL default (current_step NULL,
        # section_status '{}').
        set_clauses = ["updated_by_user_id = :actor", "updated_at = now()"]
        params: dict[str, Any] = {"tid": tenant_id, "actor": actor_user_id}
        insert_cols = ["tenant_id", "created_by_user_id", "updated_by_user_id"]
        insert_vals = [":tid", ":actor", ":actor"]
        if current_step_set:
            params["current_step"] = current_step
            insert_cols.append("current_step")
            insert_vals.append(":current_step")
            set_clauses.append("current_step = :current_step")
        if section_status_set:
            params["section_status"] = _as_jsonb(section_status)
            insert_cols.append("section_status")
            insert_vals.append("CAST(:section_status AS jsonb)")
            set_clauses.append("section_status = CAST(:section_status AS jsonb)")

        await session.execute(
            text(
                f"""
                INSERT INTO {schema}.tenant_onboarding (
                    {", ".join(insert_cols)}
                ) VALUES (
                    {", ".join(insert_vals)}
                )
                ON CONFLICT (tenant_id) DO UPDATE SET
                    {", ".join(set_clauses)}
                """
            ),
            params,
        )
        await self._emit(
            session,
            auth=auth,
            request_id=request_id,
            action="UPDATE_ONBOARDING",
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            snapshot={
                "section": "onboarding_state",
                "current_step": current_step if current_step_set else None,
            },
        )
        session.expire_all()
        state = await self.get_onboarding_state(session, tenant_id)
        assert state is not None  # tenant was visible above
        return state

    # ------------------------------------------------------------------
    # Shared audit emission
    # ------------------------------------------------------------------

    async def _emit(
        self,
        session: AsyncSession,
        *,
        auth: AuthContext | None,
        request_id: UUID | None,
        action: str,
        tenant_id: UUID,
        tenant_name: str,
        snapshot: dict[str, Any],
    ) -> None:
        if not _emit_args_valid(auth, request_id):
            return
        assert auth is not None and request_id is not None
        await emit_audit_event(
            session,
            auth=auth,
            action=action,
            resource_type="TENANT",
            resource_id=tenant_id,
            resource_label=tenant_name,
            result_type=AuditResultType.SUCCESS,
            details=build_success_details_for_create(snapshot),
            tenant_id=tenant_id,
            tenant_name=tenant_name,
            request_id=request_id,
            route_to_platform=False,
        )


def _as_jsonb(value: dict[str, Any] | None) -> str:
    import json

    return json.dumps(value if value is not None else {})
