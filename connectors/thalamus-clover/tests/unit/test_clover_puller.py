"""Unit tests for the hardened Clover transport (``CloverPuller``).

Every request is served by an ``httpx.MockTransport`` handler (no network). Backoff waits go
through an injected fake ``sleep`` so nothing actually sleeps. Covers: merchant-scoped
paths, bearer auth, offset pagination and the short-page terminator, the 1000 cap, the
expand guard, 429 / 5xx / network retry with a fake clock, attempt-cap exhaustion to a typed
error, and the rate-limit posture.
"""

from __future__ import annotations

import random
from collections.abc import Callable

import httpx
import pytest

from thalamus_clover.puller import CloverPuller
from thalamus_connector_sdk import (
    RATE_LIMIT_THROTTLED,
    ConnectorAuthError,
    ConnectorExtractError,
    ConnectorReasonCode,
)

_BASE = "https://sandbox.dev.clover.test"
_TOKEN = "sandbox-access-token"
_M = "0RKKDBMKPAH71"

Handler = Callable[[httpx.Request], httpx.Response]


class _FakeClock:
    def __init__(self) -> None:
        self.waits: list[float] = []

    def __call__(self, seconds: float) -> None:
        self.waits.append(seconds)


def _puller(
    handler: Handler, *, max_attempts: int = 5, clock: _FakeClock | None = None, page_limit: int = 1000
) -> CloverPuller:
    return CloverPuller(
        base_url=_BASE,
        client=httpx.Client(transport=httpx.MockTransport(handler), base_url=_BASE),
        max_attempts=max_attempts,
        sleep=clock or _FakeClock(),
        rng=random.Random(0),  # seeded: deterministic jitter, still exercises the code path
        page_limit=page_limit,
    )


def _elements(rows: list[dict[str, object]]) -> httpx.Response:
    return httpx.Response(200, json={"elements": rows, "href": "x"})


def _sequence(specs: list[object]) -> tuple[Handler, list[httpx.Request]]:
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


def _always(response: httpx.Response) -> tuple[Handler, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return response

    return handler, seen


# -- request shape ---------------------------------------------------------------------


def test_paths_are_merchant_scoped_and_versioned() -> None:
    handler, seen = _always(_elements([]))
    _puller(handler).list_categories(_TOKEN, _M)
    assert seen[0].url.path == f"/v3/merchants/{_M}/categories"


def test_bearer_token_on_every_request() -> None:
    handler, seen = _always(_elements([]))
    _puller(handler).list_item_stocks(_TOKEN, _M)
    assert seen[0].headers["authorization"] == f"Bearer {_TOKEN}"


def test_get_merchant_expands_properties_where_currency_lives() -> None:
    handler, seen = _always(httpx.Response(200, json={"id": _M, "properties": {"defaultCurrency": "USD"}}))
    merchant = _puller(handler).get_merchant(_TOKEN, _M)
    assert seen[0].url.params["expand"] == "properties"
    assert merchant["properties"]["defaultCurrency"] == "USD"


# -- offset pagination -------------------------------------------------------------------


def test_full_page_yields_a_next_cursor_and_short_page_ends_it() -> None:
    # There is no continuation token: a SHORT page is the only end-of-collection signal.
    handler, _ = _always(_elements([{"id": f"I{i}", "categories": {"elements": []}} for i in range(2)]))
    page = _puller(handler, page_limit=2).list_items(_TOKEN, _M, None)
    assert page.next_cursor == "2"

    handler, _ = _always(_elements([{"id": "I0", "categories": {"elements": []}}]))
    assert _puller(handler, page_limit=2).list_items(_TOKEN, _M, None).next_cursor is None


def test_cursor_is_the_offset_and_is_sent_back() -> None:
    handler, seen = _always(_elements([]))
    _puller(handler, page_limit=50).list_items(_TOKEN, _M, "150")
    assert seen[0].url.params["offset"] == "150"
    assert seen[0].url.params["limit"] == "50"


def test_page_limit_never_exceeds_the_vendor_cap() -> None:
    # Clover 400s above 1000: {"message":"limit cannot be greater than 1000"}.
    handler, seen = _always(_elements([]))
    _puller(handler, page_limit=99999).list_categories(_TOKEN, _M)
    assert int(seen[0].url.params["limit"]) == 1000


def test_a_non_numeric_cursor_is_a_typed_error() -> None:
    handler, _ = _always(_elements([]))
    with pytest.raises(ConnectorExtractError) as exc:
        _puller(handler).list_items(_TOKEN, _M, "not-an-offset")
    assert exc.value.reason is ConnectorReasonCode.SCHEMA_UNRECOGNIZED


def test_internally_exhausted_collections_follow_the_offset() -> None:
    full = _elements([{"id": f"C{i}"} for i in range(2)])
    short = _elements([{"id": "C2"}])
    handler, seen = _sequence([full, short])
    cats = _puller(handler, page_limit=2).list_categories(_TOKEN, _M)
    assert sorted(cats) == ["C0", "C1", "C2"]
    assert [r.url.params["offset"] for r in seen] == ["0", "2"]


# -- the expand guard ---------------------------------------------------------------------


def test_missing_categories_key_on_a_non_empty_page_raises() -> None:
    # Clover returns 200 for an unrecognised expand, so a silent failure would look exactly
    # like a merchant who categorises nothing. That must never be mistaken for success.
    handler, _ = _always(_elements([{"id": "I1"}, {"id": "I2"}]))
    with pytest.raises(ConnectorExtractError) as exc:
        _puller(handler).list_items(_TOKEN, _M, None)
    assert exc.value.reason is ConnectorReasonCode.SCHEMA_UNRECOGNIZED
    assert "expand" in str(exc.value)


def test_a_merchant_who_categorises_nothing_is_not_an_error() -> None:
    # The distinguishing signal: when the expand WORKS the key is present-but-empty.
    handler, _ = _always(_elements([{"id": "I1", "categories": {"elements": []}}]))
    page = _puller(handler).list_items(_TOKEN, _M, None)
    assert len(page.items) == 1


def test_an_empty_page_proves_nothing_and_does_not_raise() -> None:
    handler, _ = _always(_elements([]))
    assert _puller(handler).list_items(_TOKEN, _M, None).items == []


def test_stock_is_a_separate_call_never_an_expand() -> None:
    # itemStock absence is LEGITIMATE for an untracked item, so key-presence cannot guard
    # it. Fetching the collection keeps the failure detectable. If someone folds this into
    # expand=itemStock, this test fails.
    handler, seen = _always(_elements([]))
    _puller(handler).list_item_stocks(_TOKEN, _M)
    assert seen[0].url.path.endswith("/item_stocks")
    assert "expand" not in seen[0].url.params


def test_item_stocks_maps_item_id_to_quantity() -> None:
    handler, _ = _always(
        _elements([{"item": {"id": "A"}, "quantity": 5}, {"item": {"id": "B"}, "quantity": 0}])
    )
    assert _puller(handler).list_item_stocks(_TOKEN, _M) == {"A": "5", "B": "0"}


def test_a_stock_stub_without_a_quantity_is_not_a_zero() -> None:
    # Observed on the sandbox: /item_stocks/{id} can return {"item": {...}} with no
    # quantity. That is "not counted", and must not become a stock level of zero.
    handler, _ = _always(_elements([{"item": {"id": "A"}}]))
    assert _puller(handler).list_item_stocks(_TOKEN, _M) == {}


# -- transport hardening --------------------------------------------------------------------


def test_401_is_a_typed_auth_error_without_retry() -> None:
    handler, seen = _always(httpx.Response(401, json={"message": "401 Unauthorized"}))
    with pytest.raises(ConnectorAuthError) as exc:
        _puller(handler).get_merchant(_TOKEN, _M)
    assert exc.value.reason is ConnectorReasonCode.AUTH_FAILED
    assert len(seen) == 1  # never retried


def test_429_backoff_then_success_uses_the_fake_clock() -> None:
    clock = _FakeClock()
    handler, seen = _sequence([httpx.Response(429, text="slow down"), _elements([])])
    _puller(handler, clock=clock).list_categories(_TOKEN, _M)
    assert len(seen) == 2
    assert len(clock.waits) == 1
    assert 0 < clock.waits[0] <= 20.0


def test_retry_after_is_honoured_defensively_when_present() -> None:
    # Clover sent no Retry-After on any probed response; we honour it if it ever appears.
    clock = _FakeClock()
    handler, _ = _sequence([httpx.Response(429, headers={"Retry-After": "7"}), _elements([])])
    _puller(handler, clock=clock).list_categories(_TOKEN, _M)
    assert clock.waits == [7.0]


def test_transient_5xx_and_network_errors_retry() -> None:
    clock = _FakeClock()
    handler, seen = _sequence([httpx.Response(503), httpx.ConnectError("boom"), _elements([])])
    _puller(handler, clock=clock).list_categories(_TOKEN, _M)
    assert len(seen) == 3


def test_exhausted_429_raises_rate_limited() -> None:
    handler, _ = _always(httpx.Response(429, text="slow down"))
    with pytest.raises(ConnectorExtractError) as exc:
        _puller(handler, max_attempts=3, clock=_FakeClock()).list_categories(_TOKEN, _M)
    assert exc.value.reason is ConnectorReasonCode.RATE_LIMITED


def test_exhausted_5xx_raises_vendor_unavailable() -> None:
    handler, _ = _always(httpx.Response(503, text="down"))
    with pytest.raises(ConnectorExtractError) as exc:
        _puller(handler, max_attempts=2, clock=_FakeClock()).list_categories(_TOKEN, _M)
    assert exc.value.reason is ConnectorReasonCode.VENDOR_UNAVAILABLE


def test_non_retryable_4xx_carries_a_bounded_excerpt() -> None:
    handler, seen = _always(httpx.Response(400, json={"message": "limit cannot be greater than 1000"}))
    with pytest.raises(ConnectorExtractError) as exc:
        _puller(handler).list_categories(_TOKEN, _M)
    assert len(seen) == 1
    assert "limit cannot be greater" in (exc.value.detail or "")
    assert len(exc.value.detail or "") <= 512


# -- rate-limit posture -----------------------------------------------------------------------


def test_posture_is_none_on_a_clean_run() -> None:
    # None is what CLEARS a stored posture on the next healthy emit.
    handler, _ = _always(_elements([]))
    p = _puller(handler)
    p.list_categories(_TOKEN, _M)
    assert p.rate_limit_state() is None


def test_absorbed_429_sets_throttled() -> None:
    handler, _ = _sequence([httpx.Response(429), _elements([])])
    p = _puller(handler, clock=_FakeClock())
    p.list_categories(_TOKEN, _M)
    assert p.rate_limit_state() == RATE_LIMIT_THROTTLED


def test_a_retryable_5xx_is_not_throttling() -> None:
    handler, _ = _sequence([httpx.Response(503), _elements([])])
    p = _puller(handler, clock=_FakeClock())
    p.list_categories(_TOKEN, _M)
    assert p.rate_limit_state() is None
