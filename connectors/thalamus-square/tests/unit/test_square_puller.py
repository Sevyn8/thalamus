"""Unit tests for the hardened Square transport (``SquarePuller``).

Every request is served by an ``httpx.MockTransport`` handler (no network). Backoff waits
go through an injected fake ``sleep`` so nothing actually sleeps; the recorded wait values
are asserted instead. Covers: auth + Square-Version headers on every request, single-page
cursor mechanics, batch_inventory internal cursor exhaustion, 429 / transient-5xx / network
retry with the fake clock, Retry-After honouring, attempt-cap exhaustion to a typed error,
non-429 4xx and 401/403 shapes, and the bounded ``detail`` excerpt.
"""

from __future__ import annotations

import json
import random
from collections.abc import Callable

import httpx
import pytest

from thalamus_connector_sdk import (
    RATE_LIMIT_THROTTLED,
    ConnectorAuthError,
    ConnectorExtractError,
    ConnectorReasonCode,
)
from thalamus_square.puller import SquarePuller

_BASE_URL = "https://connect.squareupsandbox.test"
_API_VERSION = "2026-01-22"
_TOKEN = "sandbox-access-token"

Handler = Callable[[httpx.Request], httpx.Response]


class _FakeClock:
    """Records the durations passed to ``sleep`` without sleeping."""

    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _json_response(
    status: int, payload: dict[str, object], headers: dict[str, str] | None = None
) -> httpx.Response:
    return httpx.Response(status, json=payload, headers=headers)


def _puller(
    handler: Handler,
    *,
    max_attempts: int = 5,
    clock: _FakeClock | None = None,
) -> SquarePuller:
    client = httpx.Client(transport=httpx.MockTransport(handler), base_url=_BASE_URL)
    return SquarePuller(
        base_url=_BASE_URL,
        api_version=_API_VERSION,
        client=client,
        max_attempts=max_attempts,
        sleep=clock or _FakeClock(),
        # Seeded RNG so jitter is deterministic; still exercises the jitter code path.
        rng=random.Random(0),
    )


def _sequence(specs: list[object]) -> tuple[Handler, list[httpx.Request]]:
    """A handler that returns/raises each spec in order; also records every request.

    A spec is either an ``httpx.Response`` (returned) or an ``Exception`` (raised).
    """

    seen: list[httpx.Request] = []
    remaining = list(specs)

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        spec = remaining.pop(0)
        if isinstance(spec, Exception):
            raise spec
        assert isinstance(spec, httpx.Response)
        return spec

    return handler, seen


def _always(spec_factory: Callable[[httpx.Request], httpx.Response]) -> tuple[Handler, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return spec_factory(request)

    return handler, seen


# --------------------------------------------------------------------------------------
# Headers present on every request
# --------------------------------------------------------------------------------------


def test_auth_and_version_headers_on_every_request() -> None:
    handler, seen = _always(
        lambda req: _json_response(
            200,
            {
                "locations": [],
                "objects": [],
                "counts": [],
                "orders": [],
            },
        )
    )
    puller = _puller(handler)

    puller.list_locations(_TOKEN)
    puller.list_catalog(_TOKEN, cursor=None)
    puller.batch_inventory(_TOKEN, catalog_object_ids=["A"], location_ids=["L"])
    puller.search_orders(_TOKEN, location_ids=["L"], cursor=None)

    assert len(seen) == 4
    for request in seen:
        assert request.headers["Authorization"] == f"Bearer {_TOKEN}"
        assert request.headers["Square-Version"] == _API_VERSION


# --------------------------------------------------------------------------------------
# Cursor mechanics: single-page list calls, internal inventory exhaustion
# --------------------------------------------------------------------------------------


def test_list_catalog_returns_single_page_and_cursor() -> None:
    handler, seen = _sequence(
        [
            _json_response(
                200,
                {
                    "objects": [
                        {"type": "ITEM", "id": "item-1"},
                        {"type": "CATEGORY", "id": "cat-1", "category_data": {"name": "Drinks"}},
                    ],
                    "cursor": "PAGE2",
                },
            )
        ]
    )
    page = _puller(handler).list_catalog(_TOKEN, cursor=None)

    assert [obj["id"] for obj in page.items] == ["item-1"]
    assert page.categories == {"cat-1": "Drinks"}
    assert page.next_cursor == "PAGE2"
    # Single page only: the transport must NOT follow the cursor itself here.
    assert len(seen) == 1


def test_list_catalog_forwards_incoming_cursor() -> None:
    handler, seen = _sequence([_json_response(200, {"objects": [], "cursor": None})])
    _puller(handler).list_catalog(_TOKEN, cursor="INCOMING")

    assert dict(seen[0].url.params)["cursor"] == "INCOMING"
    assert dict(seen[0].url.params)["types"] == "ITEM,CATEGORY"


def test_search_orders_returns_single_page_and_cursor() -> None:
    handler, seen = _sequence([_json_response(200, {"orders": [{"id": "o1"}], "cursor": "NEXT"})])
    page = _puller(handler).search_orders(_TOKEN, location_ids=["L1"], cursor=None)

    assert [o["id"] for o in page.orders] == ["o1"]
    assert page.next_cursor == "NEXT"
    assert len(seen) == 1


def test_batch_inventory_exhausts_cursor_internally() -> None:
    handler, seen = _sequence(
        [
            _json_response(
                200,
                {
                    "counts": [{"catalog_object_id": "A", "quantity": "3"}],
                    "cursor": "PAGE2",
                },
            ),
            _json_response(
                200,
                {
                    "counts": [{"catalog_object_id": "B", "quantity": "7"}],
                    "cursor": None,
                },
            ),
        ]
    )
    result = _puller(handler).batch_inventory(_TOKEN, catalog_object_ids=["A", "B"], location_ids=["L1"])

    assert result == {"A": "3", "B": "7"}
    # Two requests: the transport followed the inventory cursor to completion.
    assert len(seen) == 2
    second_body = json.loads(seen[1].content)
    assert second_body["cursor"] == "PAGE2"


def test_batch_inventory_empty_ids_makes_no_request() -> None:
    handler, seen = _always(lambda req: _json_response(200, {"counts": []}))
    result = _puller(handler).batch_inventory(_TOKEN, catalog_object_ids=[], location_ids=["L"])

    assert result == {}
    assert seen == []


# --------------------------------------------------------------------------------------
# Rate-limit / transient retry with the fake clock
# --------------------------------------------------------------------------------------


def test_429_backoff_then_success_uses_fake_clock() -> None:
    clock = _FakeClock()
    handler, seen = _sequence(
        [
            httpx.Response(429, text="slow down"),
            httpx.Response(429, text="slow down"),
            _json_response(200, {"locations": [{"id": "L1"}]}),
        ]
    )
    result = _puller(handler, clock=clock).list_locations(_TOKEN)

    assert [loc["id"] for loc in result] == ["L1"]
    assert len(seen) == 3
    # Two waits (before attempts 2 and 3); every wait bounded and positive.
    assert len(clock.waits) == 2
    assert all(0 < w <= 20.0 for w in clock.waits)


def test_retry_after_header_is_honoured() -> None:
    clock = _FakeClock()
    handler, _ = _sequence(
        [
            httpx.Response(429, text="slow down", headers={"Retry-After": "7"}),
            _json_response(200, {"locations": []}),
        ]
    )
    _puller(handler, clock=clock).list_locations(_TOKEN)

    assert clock.waits == [7.0]


def test_transient_5xx_retried_then_success() -> None:
    clock = _FakeClock()
    handler, seen = _sequence(
        [
            httpx.Response(503, text="unavailable"),
            _json_response(200, {"objects": [], "cursor": None}),
        ]
    )
    _puller(handler, clock=clock).list_catalog(_TOKEN, cursor=None)

    assert len(seen) == 2
    assert len(clock.waits) == 1


def test_network_error_retried_then_success() -> None:
    clock = _FakeClock()
    handler, seen = _sequence(
        [
            httpx.ConnectError("connection reset"),
            _json_response(200, {"locations": []}),
        ]
    )
    _puller(handler, clock=clock).list_locations(_TOKEN)

    assert len(seen) == 2
    assert len(clock.waits) == 1


# --------------------------------------------------------------------------------------
# Attempt-cap exhaustion to typed errors
# --------------------------------------------------------------------------------------


def test_429_exhaustion_raises_rate_limited_with_excerpt() -> None:
    clock = _FakeClock()
    handler, seen = _always(lambda req: httpx.Response(429, text="RATE LIMIT BODY"))
    with pytest.raises(ConnectorExtractError) as exc_info:
        _puller(handler, max_attempts=3, clock=clock).list_locations(_TOKEN)

    err = exc_info.value
    assert err.reason is ConnectorReasonCode.RATE_LIMITED
    assert err.detail == "RATE LIMIT BODY"
    assert len(seen) == 3  # attempt cap
    assert len(clock.waits) == 2  # one wait before each retry


def test_5xx_exhaustion_raises_vendor_unavailable() -> None:
    handler, seen = _always(lambda req: httpx.Response(503, text="down"))
    with pytest.raises(ConnectorExtractError) as exc_info:
        _puller(handler, max_attempts=2).list_locations(_TOKEN)

    assert exc_info.value.reason is ConnectorReasonCode.VENDOR_UNAVAILABLE
    assert len(seen) == 2


def test_network_error_exhaustion_raises_vendor_unavailable() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        raise httpx.ConnectError("boom")

    with pytest.raises(ConnectorExtractError) as exc_info:
        _puller(handler, max_attempts=2).list_locations(_TOKEN)

    assert exc_info.value.reason is ConnectorReasonCode.VENDOR_UNAVAILABLE
    assert len(seen) == 2


# --------------------------------------------------------------------------------------
# Non-retryable error shapes
# --------------------------------------------------------------------------------------


def test_non_429_4xx_raises_extract_error_with_excerpt_no_retry() -> None:
    clock = _FakeClock()
    handler, seen = _sequence([httpx.Response(400, text="bad request detail")])
    with pytest.raises(ConnectorExtractError) as exc_info:
        _puller(handler, clock=clock).list_locations(_TOKEN)

    err = exc_info.value
    assert err.reason is ConnectorReasonCode.VENDOR_UNAVAILABLE
    assert err.detail == "bad request detail"
    assert len(seen) == 1  # no retry on a non-retryable 4xx
    assert clock.waits == []


@pytest.mark.parametrize("status", [401, 403])
def test_auth_statuses_raise_auth_error_no_retry(status: int) -> None:
    clock = _FakeClock()
    handler, seen = _sequence([httpx.Response(status, text="unauthorized")])
    with pytest.raises(ConnectorAuthError) as exc_info:
        _puller(handler, clock=clock).list_locations(_TOKEN)

    assert exc_info.value.reason is ConnectorReasonCode.AUTH_FAILED
    assert len(seen) == 1
    assert clock.waits == []


def test_detail_excerpt_is_bounded() -> None:
    handler, _ = _sequence([httpx.Response(400, text="x" * 5000)])
    with pytest.raises(ConnectorExtractError) as exc_info:
        _puller(handler).list_locations(_TOKEN)

    detail = exc_info.value.detail
    assert detail is not None
    assert len(detail) == 512


# -- the rate-limit posture the connector-health emit writes -----------------
#
# Coarse and boolean-equivalent by design: RATE_LIMIT_THROTTLED once a 429 has been
# ABSORBED (retried and recovered from), else None. No counts, no delays, no vendor text.


def test_posture_is_none_before_any_request() -> None:
    handler, _ = _sequence([_json_response(200, {"locations": []})])
    assert _puller(handler).rate_limit_state() is None


def test_posture_stays_none_on_a_clean_run() -> None:
    # None is what CLEARS a stored posture on the next healthy emit, so a clean run
    # reporting anything else would latch the surface to 'rate_limited'.
    handler, _ = _sequence([_json_response(200, {"locations": [{"id": "L1"}]})])
    puller = _puller(handler)
    puller.list_locations(_TOKEN)
    assert puller.rate_limit_state() is None


def test_absorbed_429_sets_throttled() -> None:
    handler, _ = _sequence(
        [
            httpx.Response(429, text="slow down"),
            _json_response(200, {"locations": [{"id": "L1"}]}),
        ]
    )
    puller = _puller(handler, clock=_FakeClock())
    puller.list_locations(_TOKEN)
    assert puller.rate_limit_state() == RATE_LIMIT_THROTTLED


def test_retryable_5xx_is_not_a_rate_limit() -> None:
    # A transient server error is retried through the same branch, but it is not
    # throttling and must not colour the posture.
    handler, _ = _sequence(
        [
            httpx.Response(503, text="unavailable"),
            _json_response(200, {"locations": []}),
        ]
    )
    puller = _puller(handler, clock=_FakeClock())
    puller.list_locations(_TOKEN)
    assert puller.rate_limit_state() is None


def test_posture_persists_across_later_clean_calls_in_the_same_run() -> None:
    # One run's posture is "was this run throttled at all", so a later clean call must
    # not erase an earlier absorbed 429.
    handler, _ = _sequence(
        [
            httpx.Response(429, text="slow down"),
            _json_response(200, {"locations": []}),
            _json_response(200, {"objects": []}),
        ]
    )
    puller = _puller(handler, clock=_FakeClock())
    puller.list_locations(_TOKEN)
    puller.list_catalog(_TOKEN, None)
    assert puller.rate_limit_state() == RATE_LIMIT_THROTTLED


def test_exhausted_429_raises_rate_limited_and_the_pipeline_owns_that_posture() -> None:
    # At the attempt cap the puller RAISES; 'exhausted' is stamped by the pipeline off
    # this reason code, not read back off the puller (there is no ExtractResult).
    handler, _ = _sequence([httpx.Response(429, text="slow down")] * 3)
    puller = _puller(handler, max_attempts=3, clock=_FakeClock())
    with pytest.raises(ConnectorExtractError) as exc_info:
        puller.list_locations(_TOKEN)
    assert exc_info.value.reason is ConnectorReasonCode.RATE_LIMITED
