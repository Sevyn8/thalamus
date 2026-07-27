"""thalamus_connector_sdk - the vendor-agnostic connector receiver seam (Path A).

The adapter Protocol and its types, the run trigger, the stable reason vocabulary, the
structural preflight, the CSV serializer, the data-plane config, and the
``ConnectorPipeline`` that lands template-mappable CSV in bronze and publishes
``ingress.ready`` by reusing csv-ingest-worker's bronze and publisher seams. Identity and
``trace_id`` are read off the trigger, never minted; ``dis_core.identity`` is never
imported (a test enforces it).
"""

from __future__ import annotations

from thalamus_connector_sdk.adapter import (
    DROPPED_SAMPLE_MAX,
    RATE_LIMIT_EXHAUSTED,
    RATE_LIMIT_THROTTLED,
    AuthContext,
    ConnectorAdapter,
    Cursor,
    Discovery,
    Domain,
    ExtractResult,
    ExtractRow,
    PreflightResult,
    merge_rate_limit_state,
)
from thalamus_connector_sdk.audit import ConnectorAudit
from thalamus_connector_sdk.config import SdkConfig
from thalamus_connector_sdk.csv_serialize import DELIMITER, serialize_rows
from thalamus_connector_sdk.errors import (
    ConnectorAuthError,
    ConnectorConfigError,
    ConnectorError,
    ConnectorExtractError,
)
from thalamus_connector_sdk.health import RATE_LIMIT_UNKNOWN, RateLimitState
from thalamus_connector_sdk.pipeline import (
    API_CHANNEL,
    ConnectorOutcome,
    ConnectorPipeline,
    ObjectUploader,
)
from thalamus_connector_sdk.preflight import run_preflight
from thalamus_connector_sdk.reason_codes import (
    REASON_TO_FAILURE_CODE,
    ConnectorReasonCode,
    failure_code_for_reason,
)
from thalamus_connector_sdk.trigger import ConnectorTrigger

__all__ = [
    "API_CHANNEL",
    "DELIMITER",
    "DROPPED_SAMPLE_MAX",
    "RATE_LIMIT_EXHAUSTED",
    "RATE_LIMIT_THROTTLED",
    "RATE_LIMIT_UNKNOWN",
    "REASON_TO_FAILURE_CODE",
    "AuthContext",
    "ConnectorAdapter",
    "ConnectorAudit",
    "ConnectorAuthError",
    "ConnectorConfigError",
    "ConnectorError",
    "ConnectorExtractError",
    "ConnectorOutcome",
    "ConnectorPipeline",
    "ConnectorReasonCode",
    "ConnectorTrigger",
    "Cursor",
    "Discovery",
    "Domain",
    "ExtractResult",
    "ExtractRow",
    "ObjectUploader",
    "PreflightResult",
    "RateLimitState",
    "SdkConfig",
    "failure_code_for_reason",
    "merge_rate_limit_state",
    "run_preflight",
    "serialize_rows",
]
