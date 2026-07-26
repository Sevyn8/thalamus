"""SquareTokenSet serialization + refresh-threshold logic."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from thalamus_square_oauth.payload import SquareTokenSet


def _token_set(expires_at: str) -> SquareTokenSet:
    return SquareTokenSet(
        access_token="atok",
        refresh_token="rtok",
        expires_at=expires_at,
        merchant_id="M1",
        token_type="bearer",
        scopes=("ITEMS_READ", "ORDERS_READ"),
        obtained_at="2026-07-01T00:00:00Z",
        environment="sandbox",
    )


def test_json_round_trip_preserves_every_field() -> None:
    original = _token_set("2026-08-01T00:00:00Z")
    restored = SquareTokenSet.from_json(original.to_json())
    assert restored == original


def test_needs_refresh_false_when_far_from_expiry() -> None:
    token_set = _token_set("2026-08-01T00:00:00Z")
    now = datetime(2026, 7, 1, tzinfo=UTC)
    assert token_set.needs_refresh(now=now, skew=timedelta(days=3)) is False


def test_needs_refresh_true_inside_skew_window() -> None:
    token_set = _token_set("2026-07-04T00:00:00Z")
    now = datetime(2026, 7, 2, tzinfo=UTC)  # 2 days before expiry, skew is 3 days
    assert token_set.needs_refresh(now=now, skew=timedelta(days=3)) is True


def test_needs_refresh_true_when_past_expiry() -> None:
    token_set = _token_set("2026-07-01T00:00:00Z")
    now = datetime(2026, 7, 10, tzinfo=UTC)
    assert token_set.needs_refresh(now=now, skew=timedelta(seconds=0)) is True
