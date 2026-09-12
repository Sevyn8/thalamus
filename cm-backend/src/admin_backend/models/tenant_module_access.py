"""TenantModuleAccess ORM model + module enums.

Tracks which modules each tenant is entitled to use, with full
lifecycle audit columns. Pattern (a) audit-actors per D-13: typed FKs
direct to ``platform_users``, no ``*_by_user_type`` discriminator
(modules are managed by Ithina staff only; no TENANT user_type ever
appears in audit-actor columns).

This is the real, DB-backed source of module entitlements (there is
no in-memory or stubbed fallback).

``module`` and ``status`` use ``postgresql.ENUM(..., create_type=False,
native_enum=True)`` — never ``Text`` (Postgres has no implicit
varchar -> enum cast).

``id``, ``created_at``, ``updated_at`` carry
``server_default=FetchedValue()`` so SQLAlchemy omits them
from INSERT and reads them back via RETURNING.
"""
from datetime import datetime
from enum import Enum
from uuid import UUID

from sqlalchemy import DateTime, FetchedValue, Uuid
from sqlalchemy.dialects.postgresql import ENUM as PG_ENUM
from sqlalchemy.orm import Mapped, mapped_column

from admin_backend.config import get_settings
from admin_backend.db.base import Base


# MEMBERSHIP AND ORDER BOTH MIRROR ``core.module_code_enum`` EXACTLY, and
# ``tests/integration/test_permission_enum_parity.py`` asserts it in both
# directions. A member added here without an accompanying migration is
# unwritable; a label added to the type without a member here crashes
# validation at the read boundary. Adding a value is additive (``ALTER TYPE
# ... ADD VALUE``, see ``a1c4e7f09d2b``); removing one needs the
# rename-recreate-cast dance (see ``0fdfbc8871a8``).
class ModuleCode(str, Enum):
    """Platform-fixed module codes. Mirrors ``module_code_enum`` in DDL."""

    PRICING_OS = "PRICING_OS"
    PERISHABLES_ASSISTANT = "PERISHABLES_ASSISTANT"
    PROMOTIONS_ASSISTANT = "PROMOTIONS_ASSISTANT"
    GOAL_CONSOLE = "GOAL_CONSOLE"
    ADMIN = "ADMIN"
    # DIS (Data Integration System) added to the catalog: grantable per
    # tenant via Module Access, default disabled (no seeded
    # tenant_module_access row), served at the DIS Cloud Run UI. Added to
    # ``module_code_enum`` by the DIS-module-catalog migration.
    DIS = "DIS"


class ModuleAccessStatus(str, Enum):
    """Module access lifecycle. Mirrors ``module_access_status_enum`` in DDL."""

    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class TenantModuleAccess(Base):
    """Per-tenant module entitlement row with lifecycle audit."""

    __tablename__ = "tenant_module_access"
    __table_args__ = {"schema": get_settings().db_schema}

    # ---------- Surrogate primary key ----------
    id: Mapped[UUID] = mapped_column(
        Uuid, primary_key=True, server_default=FetchedValue()
    )

    # ---------- Identity ----------
    tenant_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    module: Mapped[ModuleCode] = mapped_column(
        PG_ENUM(
            ModuleCode,
            name="module_code_enum",
            create_type=False,
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )
    status: Mapped[ModuleAccessStatus] = mapped_column(
        PG_ENUM(
            ModuleAccessStatus,
            name="module_access_status_enum",
            create_type=False,
            native_enum=True,
            values_callable=lambda e: [m.value for m in e],
        ),
        nullable=False,
    )

    # ---------- Lifecycle ----------
    enabled_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    enabled_by_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    disabled_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    disabled_by_user_id: Mapped[UUID | None] = mapped_column(
        Uuid, nullable=True
    )

    # ---------- Audit (Pattern (a) per D-13) ----------
    # FK declarations live at the DB layer; no SA-level relationship()
    # to PlatformUser is modelled here (matches the project convention
    # used by the other audit-actor columns in this package).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=FetchedValue(),
    )
    created_by_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=FetchedValue(),
    )
    updated_by_user_id: Mapped[UUID] = mapped_column(Uuid, nullable=False)
