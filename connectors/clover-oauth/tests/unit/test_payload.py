"""CloverTokenSet: JSON round trip, Unix-timestamp expiry logic, and the previous-token stamp."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from thalamus_clover_oauth.payload import CloverTokenSet

# 2026-08-01T12:00:00Z, and the access token expiring 30 minutes later (the measured life).
_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
_ACCESS_EXP = int(_NOW.timestamp()) + 30 * 60
_REFRESH_EXP = int(_NOW.timestamp()) + 365 * 24 * 60 * 60


def _record(**overrides: object) -> CloverTokenSet:
    base: dict[str, object] = {
        "access_token": "eyJhbGciOi.access.jwt",
        "access_token_expiration": _ACCESS_EXP,
        "refresh_token": "clvroar-current",
        "refresh_token_expiration": _REFRESH_EXP,
        "previous_refresh_token": None,
        "previous_rotated_at": None,
        "merchant_id": "0RKKDBMKPAH71",
        "employee_id": "EMP1",
        "obtained_at": int(_NOW.timestamp()),
        "environment": "sandbox",
    }
    base.update(overrides)
    return CloverTokenSet(**base)  # type: ignore[arg-type]


def test_round_trips_through_json() -> None:
    record = _record(previous_refresh_token="clvroar-previous", previous_rotated_at=1_760_000_000)
    assert CloverTokenSet.from_json(record.to_json()) == record


def test_expiries_serialise_as_integers_not_strings() -> None:
    # The Square lane stores RFC3339 strings; Clover sends epoch ints and we keep them
    # verbatim, so nothing can drift through a parse/format round trip.
    data = json.loads(_record().to_json())
    assert isinstance(data["access_token_expiration"], int)
    assert isinstance(data["refresh_token_expiration"], int)
    assert data["access_token_expiration"] == _ACCESS_EXP


def test_absent_optional_fields_decode_as_none() -> None:
    # A first record (straight out of the code exchange) has no recovery credential yet.
    record = CloverTokenSet.from_json(_record().to_json())
    assert record.previous_refresh_token is None
    assert record.previous_rotated_at is None


def test_needs_refresh_is_false_well_before_expiry() -> None:
    assert _record().needs_refresh(now=_NOW, skew=timedelta(minutes=5)) is False


def test_needs_refresh_is_true_inside_the_skew() -> None:
    inside = datetime.fromtimestamp(_ACCESS_EXP - 60, tz=UTC)
    assert _record().needs_refresh(now=inside, skew=timedelta(minutes=5)) is True


def test_needs_refresh_is_true_exactly_at_the_skew_boundary() -> None:
    boundary = datetime.fromtimestamp(_ACCESS_EXP - 300, tz=UTC)
    assert _record().needs_refresh(now=boundary, skew=timedelta(minutes=5)) is True


def test_refresh_token_expiry_is_independent_of_the_access_token() -> None:
    record = _record()
    past_access = datetime.fromtimestamp(_ACCESS_EXP + 1, tz=UTC)
    assert record.needs_refresh(now=past_access, skew=timedelta(0)) is True
    assert record.refresh_token_expired(now=past_access) is False
    past_refresh = datetime.fromtimestamp(_REFRESH_EXP + 1, tz=UTC)
    assert record.refresh_token_expired(now=past_refresh) is True


def test_carrying_previous_stamps_the_spent_token_without_touching_the_rest() -> None:
    rotated = _record(access_token="new-access", refresh_token="clvroar-new")
    stamped = rotated.carrying_previous(spent_refresh_token="clvroar-spent", rotated_at=1_770_000_000)
    assert stamped.previous_refresh_token == "clvroar-spent"
    assert stamped.previous_rotated_at == 1_770_000_000
    # Everything else is carried through untouched (frozen dataclass, replace semantics).
    assert stamped.refresh_token == "clvroar-new"
    assert stamped.access_token == "new-access"
    assert stamped.merchant_id == rotated.merchant_id
    assert rotated.previous_refresh_token is None  # the original is not mutated


def test_previous_refresh_token_survives_a_round_trip() -> None:
    # It is a LIVE ~2-week recovery credential, not history: losing it in serialisation
    # would silently remove the only path back from a lost write.
    stamped = _record().carrying_previous(spent_refresh_token="clvroar-spent", rotated_at=17)
    assert CloverTokenSet.from_json(stamped.to_json()).previous_refresh_token == "clvroar-spent"
