"""Opaque keyset-cursor encode/decode — the house pagination helper (Slice 51b, D124).

The FIRST paginated list endpoint (``GET /runs``) establishes this pattern; later
dis-ui-server list endpoints reuse it. A cursor is an OPAQUE token: callers echo it back,
never construct or parse it. It carries the keyset BOUNDARY — the ``(received_at, id)`` of the
last row on the page, over the fixed ``(received_at DESC, id DESC)`` ordering 51a established —
plus the FILTER SET it was issued under (status + window token). A cursor replayed under a
different filter set is REJECTED fail-loud, never silently re-based to page 1 (the
no-silent-fallback posture; D124).

Encoding is ``base64url(orjson(payload))`` with a version tag; it is deliberately CHANGEABLE
(callers depend only on round-trip), so nothing outside this module reads its internals. The
boundary predicate itself is a ROW-VALUE comparison ``(received_at, id) < (:r, :i)`` built in
``repos/runs.py`` — the OR-expanded form is forbidden (proven non-index-pushable, D124); this
module only carries the boundary values, it does not build SQL.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

import orjson

from dis_core.errors import InvalidCursorError

# Bump to invalidate old tokens if the payload shape ever changes (opacity guarantee).
_CURSOR_VERSION = 1


@dataclass(frozen=True)
class Boundary:
    """The keyset boundary: the last-seen row's position over ``(received_at DESC, id DESC)``."""

    received_at: datetime
    id: UUID


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(token: str) -> bytes:
    padding = "=" * (-len(token) % 4)
    return base64.urlsafe_b64decode(token + padding)


def encode_cursor(boundary: Boundary, *, status: str | None, window: str | None) -> str:
    """Opaque next-page token: the boundary plus the filter set it is valid within."""
    payload = {
        "v": _CURSOR_VERSION,
        "r": boundary.received_at.isoformat(),  # tz-aware; round-trips via fromisoformat
        "i": str(boundary.id),
        "s": status,
        "w": window,
    }
    return _b64encode(orjson.dumps(payload))


def decode_cursor(token: str, *, status: str | None, window: str | None) -> Boundary:
    """Decode a cursor from :func:`encode_cursor`, enforcing its issuing filter set.

    Fail-loud (D124): a malformed/garbage/wrong-version token ->
    ``InvalidCursorError(reason='undecodable')``; a token issued under a different
    ``status``/``window`` -> ``InvalidCursorError(reason='filter_mismatch')``. Never a guessed
    boundary and never a silent restart. ``reason`` is a fixed code, never the token bytes.
    """
    try:
        payload = orjson.loads(_b64decode(token))
        if payload["v"] != _CURSOR_VERSION:
            raise ValueError("unknown cursor version")
        boundary = Boundary(
            received_at=datetime.fromisoformat(payload["r"]),
            id=UUID(payload["i"]),
        )
        issued_status = payload["s"]
        issued_window = payload["w"]
    except (ValueError, KeyError, TypeError, orjson.JSONDecodeError):
        raise InvalidCursorError("pagination cursor is malformed", reason="undecodable") from None
    if issued_status != status or issued_window != window:
        raise InvalidCursorError(
            "pagination cursor was issued under a different filter set", reason="filter_mismatch"
        )
    return boundary


__all__ = ["Boundary", "encode_cursor", "decode_cursor"]
