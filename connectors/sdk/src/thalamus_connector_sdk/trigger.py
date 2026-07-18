"""The connector run trigger: identity, trace_id, and connector_run_id are READ here.

The trigger is the trust boundary (D54, hard rule 4). Identity (``tenant_id`` /
``store_id``), ``trace_id``, and ``connector_run_id`` are carried on it and trusted; the
receiver mints none of them and never imports ``dis_core.identity``. ``connector_run_id``
is the dedup ``source_payload_id`` component; its minting authority is the trigger
producer (scheduler), which must keep it stable across a retry of the same logical run
so the 24h dedup collapses redeliveries.
"""

from __future__ import annotations

from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from thalamus_connector_sdk.adapter import Cursor, Domain


class ConnectorTrigger(BaseModel):
    """One connector run trigger, field-shape frozen (populate, never mutate)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = Field(default=1)
    trace_id: UUID  # READ, never minted (hard rule 4)
    connector_run_id: str = Field(min_length=1)  # dedup source_payload_id
    tenant_id: UUID  # trust boundary (D54)
    store_id: UUID
    source_id: str = Field(min_length=1)
    template_id: UUID
    domains: list[Domain] = Field(min_length=1)
    cursor: Cursor | None = None  # prior high-water mark for incremental extract
    tenant_display_code: str | None = None
    store_code: str | None = None
