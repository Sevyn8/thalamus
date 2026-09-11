"""The audit writer interface and backend selection.

Consumers depend on the :class:`AuditWriter` protocol, not a concrete class;
``select_writer`` is the single construction point for the Cloud SQL writer.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Protocol, runtime_checkable

from sqlalchemy.ext.asyncio import AsyncEngine

from dis_audit.event import AuditEvent
from dis_audit.postgres_writer import PostgresAuditWriter
from dis_core.errors import AuditWriteError


@runtime_checkable
class AuditWriter(Protocol):
    """Lands one audit event, fire-and-forget. Returns ``True`` on a confirmed write.

    Implementations never raise to the caller and never block the data path (hard
    rule 11): a failure is logged with context and reported as ``False``.
    """

    async def write(self, event: AuditEvent) -> bool: ...


class AuditBackend(StrEnum):
    """The audit write backends. ``POSTGRES`` is the only backend."""

    POSTGRES = "POSTGRES"


def select_writer(
    backend: AuditBackend,
    *,
    engine: AsyncEngine | None = None,
) -> AuditWriter:
    """Return the writer for ``backend``.

    ``AuditBackend.POSTGRES`` requires a caller-owned ``engine``. No silent
    fallback for a required value: a missing engine raises.
    """
    if engine is None:
        raise AuditWriteError("AuditBackend.POSTGRES requires a caller-owned engine")
    return PostgresAuditWriter(engine)
