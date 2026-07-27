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
