"""Connector receiver errors, rooted in ``dis_core`` ``DisError`` for context.

``ConnectorError`` carries a stable :class:`ConnectorReasonCode` (never raw vendor
text) plus the tenant/trace identifiers, mirroring the csv-ingest-worker error family.
``ConnectorConfigError`` is the startup/config failure (no reason code, like the
worker's ``CsvIngestError`` config raise).
"""

from __future__ import annotations

from dis_core.errors import DisError
from thalamus_connector_sdk.reason_codes import ConnectorReasonCode


class ConnectorConfigError(DisError):
    """A required configuration value is missing or invalid (no silent fallback)."""


class ConnectorError(DisError):
    """A connector run failure carrying a stable reason code (never raw vendor text)."""

    def __init__(
        self,
        message: str,
        *,
        reason: ConnectorReasonCode,
        detail: str | None = None,
        tenant_id: str | None = None,
        trace_id: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason
        self.detail = detail
        self.tenant_id = tenant_id
        self.trace_id = trace_id


class ConnectorAuthError(ConnectorError):
    """Authentication to the vendor failed (reason AUTH_FAILED / AUTH_EXPIRING)."""


class ConnectorExtractError(ConnectorError):
    """Discovery or extract failed (RATE_LIMITED / VENDOR_UNAVAILABLE / etc.)."""
