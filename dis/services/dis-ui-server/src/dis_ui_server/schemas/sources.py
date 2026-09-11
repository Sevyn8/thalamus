"""Wire shapes for the source registry (Phase A, D112): GET /sources + POST /sources.

``channel`` reuses the ``dis_channel`` vocabulary verbatim (DB value == wire value), so it
is a passthrough ``Literal`` — no crosswalk. It is NULLable (backfill leaves it NULL when a
source has no bronze events yet). ``status`` is the operator enablement vocab.

The create body mirrors ``MappingTemplateCreate``: ``source_id`` is a validated slug, and
``acting_for_tenant_id`` carries the PLATFORM impersonation target (honoured only on a verified
``user_type=PLATFORM`` token; a TENANT naming one is 403 via ``resolve_acted_for``).
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field

# Wire vocabularies (DB value == wire value; passthrough).
ChannelWire = Literal["csv_upload", "api", "csv_erp", "reverse_api"]
StatusWire = Literal["active", "paused", "disabled"]


class SourceRow(BaseModel):
    """One registered source (fields per config.sources)."""

    tenant_id: str  # the owning tenant (config.sources.tenant_id, NOT NULL) — fleet attribution (Chunk 1)
    tenant_name: str | None  # identity_mirror.tenants.name; null when tenant unmirrored (Chunk 9)
    source_id: str
    display_name: str
    channel: ChannelWire | None  # dis_channel vocab; null when unknown
    store_id: str | None
    schedule: str | None
    status: StatusWire
    created_at: str  # ISO-8601, UTC as Z
    updated_at: str


class SourceListResponse(BaseModel):
    """The list body: the tenant's registered sources."""

    items: list[SourceRow]


class SourceCreate(BaseModel):
    """POST /sources body — register a source. ``source_id`` is a lowercase slug."""

    source_id: str = Field(pattern=r"^[a-z0-9_]{1,128}$")
    display_name: str = Field(min_length=1, max_length=256)
    channel: ChannelWire | None = None
    store_id: str | None = Field(default=None, max_length=128)
    schedule: str | None = Field(default=None, max_length=128)
    # PLATFORM impersonation target; a TENANT naming one is rejected 403.
    acting_for_tenant_id: UUID | None = None
