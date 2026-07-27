"""``identity_mirror.tenants`` — the Customer Master tenant mirror (read-only here).

Column set mirrors the LIVE table (introspected in Slice 8 plan mode): 9 columns,
PK ``tenant_id``, ``display_code`` nullable (faithful copy of CM's nullable
source column, D55). Like ``identity_mirror.stores`` the table is RLS-OFF (D41),
so there is no database backstop: every read of this model must be isolated by
the QUERY or by its CALLER, and both live in ONE place, ``repos/tenants.py``.
Do not query this model anywhere else.

A tenant-facing read carries an explicit ``tenant_id`` predicate — the in-query
scoping is then the only isolation. The one CROSS-TENANT read
(``list_actable_tenants``, the PLATFORM ops tenant list) carries none by design;
its isolation is RELOCATED, not dropped — ``handlers/tenants.py`` refuses any
caller that is not PLATFORM + ``dis:ops`` before the query runs. Adding an
unpredicated read without an equivalent caller-side gate is a cross-tenant leak.

dis-ui-server never writes this table (Mirror Sync owns it); the model is typed
read metadata only.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from sqlalchemy import DateTime, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from dis_ui_server.db import Base


class TenantRow(Base):
    """One mirrored tenant row (faithful copy of Customer Master ``core.tenants``)."""

    __tablename__ = "tenants"
    __table_args__ = {"schema": "identity_mirror"}

    tenant_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    # CHECK ck_imt_status_vocab: ONBOARDING | TRIAL | ACTIVE | SUSPENDED | TERMINATED.
    status: Mapped[str] = mapped_column(Text)
    pc_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pc_updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    pc_suspended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    pc_terminated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    mirror_synced_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Nullable at source (D55); producers populate the wire code only when present.
    display_code: Mapped[str | None] = mapped_column(Text)
