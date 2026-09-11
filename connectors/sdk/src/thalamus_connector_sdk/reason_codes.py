"""The connector's stable preflight/failure reason vocabulary.

Closure is a TYPE-LEVEL guarantee: a closed ``StrEnum`` the SDK owns. Raw vendor or
HTTP-client error text is NEVER used as a reason (it can quote payload values); only
these codes are propagated to audit and connector-health.

``dis-audit`` owns a separate CLOSED ``FailureCode`` vocabulary and the documented rule
is that service-local codes are mapped to a ``FailureCode`` at their emit site (the
csv-ingest-worker ``_PREFLIGHT_CODES`` precedent). So ``REASON_TO_FAILURE_CODE`` maps
each connector reason to an existing ``FailureCode`` member, and the connector reason
always ALSO rides ``event_data["reason"]`` (the no-information-loss rule) and is the
connector-health error detail.
"""

from __future__ import annotations

from enum import StrEnum

from dis_audit import FailureCode


class ConnectorReasonCode(StrEnum):
    """One member per connector failure path. Closed, owned vocabulary."""

    AUTH_FAILED = "AUTH_FAILED"  # credentials rejected
    AUTH_EXPIRING = "AUTH_EXPIRING"  # credentials valid but near expiry (health hint)
    RATE_LIMITED = "RATE_LIMITED"  # vendor throttled the extract
    DISCOVERY_EMPTY = "DISCOVERY_EMPTY"  # no streams/entities available
    EXTRACT_EMPTY = "EXTRACT_EMPTY"  # extract returned zero rows
    SCHEMA_UNRECOGNIZED = "SCHEMA_UNRECOGNIZED"  # vendor payload shape not mappable
    VENDOR_UNAVAILABLE = "VENDOR_UNAVAILABLE"  # vendor 5xx / network failure


# Connector-local reason -> dis-audit's closed FailureCode (mapped at the emit site).
# Structural reasons map onto the existing preflight members; auth/rate/vendor are
# infra-class. The connector reason itself is preserved in event_data["reason"].
REASON_TO_FAILURE_CODE: dict[ConnectorReasonCode, FailureCode] = {
    ConnectorReasonCode.AUTH_FAILED: FailureCode.INFRA_FAILURE,
    ConnectorReasonCode.AUTH_EXPIRING: FailureCode.INFRA_FAILURE,
    ConnectorReasonCode.RATE_LIMITED: FailureCode.INFRA_FAILURE,
    ConnectorReasonCode.DISCOVERY_EMPTY: FailureCode.INFRA_FAILURE,
    ConnectorReasonCode.EXTRACT_EMPTY: FailureCode.PREFLIGHT_NO_DATA_ROWS,
    ConnectorReasonCode.SCHEMA_UNRECOGNIZED: FailureCode.PREFLIGHT_NO_COLUMNS,
    ConnectorReasonCode.VENDOR_UNAVAILABLE: FailureCode.INFRA_FAILURE,
}


def failure_code_for_reason(reason: ConnectorReasonCode) -> FailureCode:
    """The stable ``FailureCode`` for a connector reason (every member is mapped)."""
    return REASON_TO_FAILURE_CODE[reason]
