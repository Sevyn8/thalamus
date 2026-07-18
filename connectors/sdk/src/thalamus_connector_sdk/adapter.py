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
    else None; D33/D65). The hint is informational (the streaming consumer derives
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
