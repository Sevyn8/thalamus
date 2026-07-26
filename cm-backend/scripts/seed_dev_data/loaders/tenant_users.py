"""Loader for tenant_users."""
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from scripts.seed_dev_data.column_mappings import validate_columns
from scripts.seed_dev_data.loaders._base import insert_and_register
from scripts.seed_dev_data.uuid_mapper import UUIDMapper

SHEET_NAME = "tenant_users"
TABLE_NAME = "tenant_users"


async def load(
    session: AsyncSession,
    rows: list[dict[str, Any]],
    mapper: UUIDMapper,
) -> None:
    if rows:
        validate_columns(SHEET_NAME, list(rows[0].keys()))

    # Slice 9 (one email = one identity): enforce the cross-TABLE rule the
    # DB cannot (no single constraint spans platform_users + tenant_users).
    # platform_users is loaded before tenant_users, so any tenant email
    # colliding with a platform email is a violation. Tenant-vs-tenant
    # dups (same email in two tenant_users rows) are caught by the global
    # uq_tenant_users_email index at INSERT; this pre-check adds a clear,
    # actionable message for both cases before the raw IntegrityError.
    platform_emails = {
        r[0]
        for r in (
            await session.execute(text("SELECT email FROM platform_users"))
        ).all()
    }
    seen: set[str] = set()
    for row in rows:
        email = row.get("email")
        if email in platform_emails:
            raise ValueError(
                f"seed tenant_users email {email!r} already exists in "
                "platform_users (Slice 9: one email = one identity). "
                "Fix the seed data before loading."
            )
        if email in seen:
            raise ValueError(
                f"seed tenant_users email {email!r} appears in more than "
                "one tenant_users row (Slice 9: one email = one identity). "
                "Fix the seed data before loading."
            )
        seen.add(email)
        await insert_and_register(
            session, SHEET_NAME, TABLE_NAME, row, mapper
        )
