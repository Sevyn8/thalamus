"""The vendor-agnostic connector seam: the ``ConnectorAdapter`` Protocol and its types.

A structural ``Protocol`` (tests inject fakes; production never imports test doubles),
the seam every connector implements. The pipeline drives it: authenticate, then extract
one or more domains (cursor incremental), then structural preflight.

Rows are template-mappable: each :class:`ExtractRow` is a dict keyed by the target
template field keys, all values strings (the CSV cell shape). The CSV header the
pipeline writes is :attr:`ExtractResult.header`, which IS the interface to the mapping
template. The connector never calls ``dis-mapping``; it produces source-shaped rows a
template maps.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Protocol

from thalamus_connector_sdk.reason_codes import ConnectorReasonCode

if TYPE_CHECKING:
    from thalamus_connector_sdk.trigger import ConnectorTrigger

# An opaque vendor incremental token (pagination cursor / high-water time). The SDK
# treats it as opaque text; only the adapter interprets it.
type Cursor = str


# The bound on the non-PII dropped-identifier sample carried on the RECEIVED audit
# (the full count is exact; the sample is a diagnostic aid, not an inventory).
DROPPED_SAMPLE_MAX = 20

# The coarse rate-limit posture vocabulary for telemetry.connector_health.rate_limit_state
# . Deliberately two values and NULL - no counts, no wait durations, no vendor text:
# the read side (dis-ui-server derive_status) treats ANY non-null as 'rate_limited', so the
# column is a posture, not a metric.
#
#   RATE_LIMIT_THROTTLED  the adapter absorbed >=1 vendor rate-limit response during this
#                         run and still completed the extract.
#   RATE_LIMIT_EXHAUSTED  the retry budget ran out on a rate-limit response; the run FAILED
#                         with ConnectorReasonCode.RATE_LIMITED. Stamped by the pipeline off
#                         the error, not carried on an ExtractResult (there is none).
#   None                  no rate-limit response observed.
RATE_LIMIT_THROTTLED = "throttled"
RATE_LIMIT_EXHAUSTED = "exhausted"

# Most-severe-first ordering, used to fold the per-domain postures of a multi-domain
# trigger into one (see ConnectorPipeline._extract_all).
_RATE_LIMIT_SEVERITY: dict[str, int] = {RATE_LIMIT_THROTTLED: 1, RATE_LIMIT_EXHAUSTED: 2}


def merge_rate_limit_state(current: str | None, incoming: str | None) -> str | None:
    """Fold two postures, most severe wins. None is the least severe (nothing observed)."""
    if current is None:
        return incoming
    if incoming is None:
        return current
    return max(current, incoming, key=lambda state: _RATE_LIMIT_SEVERITY.get(state, 0))


class Domain(StrEnum):
    """The closed extract-domain vocabulary."""

    CATALOG = "CATALOG"
    INVENTORY = "INVENTORY"
    ORDERS = "ORDERS"


@dataclass(frozen=True)
class AuthContext:
    """The authenticated vendor session an extract runs under.

    ``token`` is the vendor access token; ``store_by_code`` maps a vendor location to
    the DIS store_code (readability only); ``extra`` carries vendor-specific handles.
    Never logged.
    """

    token: str
    expires_at: datetime | None = None
    store_by_code: dict[str, str] = field(default_factory=dict)
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class Discovery:
    """What ``discover`` found: locations to seed store resolution and the vendor
    native schema to seed a template proposal (never mapping itself)."""

    locations: tuple[str, ...]
    native_schema: dict[str, Any]


@dataclass(frozen=True)
class ExtractRow:
    """One template-mappable row: template-field-keyed string cells, plus the
    per-row ``source_event_id`` hint (``transaction_id:line_item_seq`` for ORDERS,
    else None). The hint is informational (the streaming consumer derives
    ``source_event_id`` itself from the mapped columns)."""

    values: dict[str, str]
    source_event_id_hint: str | None = None


@dataclass(frozen=True)
class ExtractResult:
    """One domain's extracted, shaped batch plus the next cursor.

    ``header`` is the ordered CSV column set (target template field keys). ``rows``
    carry only keys present in ``header``; a missing cell is written blank.
    """

    domain: Domain
    header: tuple[str, ...]
    rows: tuple[ExtractRow, ...]
    next_cursor: Cursor | None
    # Rows the adapter excluded as unmappable (e.g. a Square variation with no price):
    # a count + a bounded, non-PII sample of identifiers for the RECEIVED audit. The
    # rows are already out of ``rows``; this is the visibility signal, not a second path.
    dropped_count: int = 0
    dropped_sample: tuple[str, ...] = ()
    # The coarse rate-limit posture OBSERVED WHILE PRODUCING THIS RESULT: the
    # RATE_LIMIT_THROTTLED constant when the adapter absorbed a vendor rate-limit response
    # and still completed, else None. Rides this object for the same reason dropped_count
    # does - it is a per-extract diagnostic the vendor-agnostic pipeline forwards to the
    # health emit. An extract that EXHAUSTED its retry budget raises instead, so
    # RATE_LIMIT_EXHAUSTED never appears here; the pipeline stamps it off the error.
    #
    # None here is a POSITIVE assertion ("no rate-limit response this run"), not ignorance:
    # the pipeline writes it authoritatively and it is what clears a stored posture.
    rate_limit_state: str | None = None


@dataclass(frozen=True)
class PreflightResult:
    """The structural preflight verdict. Structural ONLY: no cell inspection, no
    mapping-aware checks. On failure ``reason`` is a stable code, never vendor text."""

    ok: bool
    row_count: int
    columns: tuple[str, ...]
    reason: ConnectorReasonCode | None = None
    detail: str | None = None


class ConnectorAdapter(Protocol):
    """The seam a connector implements. Cursor-incremental extract over the domains."""

    def authenticate(self, trigger: ConnectorTrigger) -> AuthContext: ...

    def discover(self, auth: AuthContext) -> Discovery: ...

    def extract(self, auth: AuthContext, domain: Domain, cursor: Cursor | None) -> ExtractResult: ...

    def preflight(self, extract: ExtractResult) -> PreflightResult: ...
