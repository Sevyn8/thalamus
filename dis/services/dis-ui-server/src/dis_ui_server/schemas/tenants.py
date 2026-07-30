"""Wire shape for ``GET /tenants-actable`` (bare array of these; §2.4 no envelope).

Vocabulary note (§2.6 — the BFF owns translation, DB vocab never leaks): the mirror's
CHECK vocabulary (``ONBOARDING|TRIAL|ACTIVE|SUSPENDED|TERMINATED``) is served lowercased
and the wire ``Literal`` pins the translation, so a new DB vocab member fails loud here
instead of leaking untranslated.

``terminated`` IS ABSENT FROM THE LITERAL ON PURPOSE, and that is a second guard rather
than an oversight: ``repos/tenants.py`` excludes the end state from the query, and if that
filter were ever removed this Literal turns the regression into a loud 500 instead of a
terminated tenant quietly appearing in an onboarding picker. Every OTHER status is served,
including ``suspended`` — the client decides what a suspended tenant may be used for
(today: shown, disabled, status visible), because that policy is unsettled and does not
belong baked into a read.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

TenantStatus = Literal["onboarding", "trial", "active", "suspended"]


class ActableTenant(BaseModel):
    """One tenant a PLATFORM ops caller may act for, from ``identity_mirror.tenants``."""

    tenant_id: str  # internal UUID, lowercase string (the acted-for id, §2.2)
    name: str
    display_code: str | None  # nullable at source (D55) — served as-is, never invented
    status: TenantStatus


class TenantSelf(BaseModel):
    """The CALLER'S OWN tenant, for the topbar's identity chip (``GET /tenant-self``).

    BOTH DISPLAY FIELDS ARE NULLABLE, and that is the contract rather than a weakness.
    ``display_code`` is nullable at source (D55). ``name`` is nullable for a different
    reason: ``identity_mirror`` is EVENTUALLY CONSISTENT, so a tenant onboarded in Customer
    Master since the last mirror-sync run legitimately has no row here. That case is served
    as a 200 with nulls, NEVER a 404 — the client falls back to the UUID, and mirror lag must
    not be the thing that breaks a topbar.

    No ``status``: unlike ``ActableTenant`` this is not a picker feeding a decision about
    what a tenant may be used for. It is a display label for the tenant the caller already
    is, so status would be a field nobody reads.
    """

    tenant_id: str  # the caller's own tenant, echoed from the verified token
    name: str | None  # None when the mirror has no row yet (lag), not an error
    display_code: str | None  # nullable at source (D55) — served as-is, never invented
