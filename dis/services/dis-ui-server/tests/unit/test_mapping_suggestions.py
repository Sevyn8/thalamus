"""Unit tests for the mapping-suggestions handler + the GeminiSuggester.

The handler is exercised through the production ``create_app`` factory with the
new router mounted via the ``extra_api_routers`` test seam (so api.py is NOT
edited this phase), a fake suggester injected on ``app.state.gemini``, and
dev-stub Bearer tokens from the shared ``mint_token`` fixture. The GeminiSuggester
is tested directly: key-unset and model-error degrade to the mechanical fallback,
a clean response parses to ``source="llm"``, and a non-catalog target is nulled.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from typing import Any, cast

import anyio
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dis_ui_server.catalog import build_field_catalog
from dis_ui_server.handlers import mapping_suggestions
from dis_ui_server.main import create_app
from dis_ui_server.schemas.mapping_suggestions import ColumnProfile, Suggestion
from dis_ui_server.suggest.gemini_client import GeminiSuggester

CATALOG = build_field_catalog()
CATALOG_KEYS = {field.key for field in CATALOG}

_BODY = {
    "columns": [{"name": "qty", "inferred_datatype": "integer", "null_pct": 0.0, "sample_values": ["1", "2"]}]
}


class _FakeSuggester:
    """Stands in for app.state.gemini; returns a canned (source, model, suggestions)."""

    def __init__(self, result: tuple[str, str | None, list[Suggestion]]) -> None:
        self._result = result

    async def suggest(self, columns, catalog):  # type: ignore[no-untyped-def]
        return self._result


@pytest.fixture
def suggest_client(monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """The app with the mapping-suggestions router mounted via the test seam.

    Same unreachable-backend env as the shared ``client`` fixture; the lifespan
    builds ``app.state.field_catalog``. ``app.state.gemini`` is wired by a later
    phase, so each test sets it to a fake after startup.
    """
    monkeypatch.setenv("POSTGRES_URL", "postgresql+psycopg://u:p@127.0.0.1:9/ithina_dis_db")
    # DIS_AUTH_MODE is DECLARED because this module builds its own environment rather than
    # going through conftest's set_unit_env. The default is AUTH0, which requires an issuer
    # and an audience; these tests want the HS256 stub, and the URL above is loopback, which
    # is what the stub guard requires.
    monkeypatch.setenv("DIS_AUTH_MODE", "STUB")
    monkeypatch.setenv("GCS_BUCKET_BRONZE", "ithina-bronze-raw")
    monkeypatch.setenv("PUBSUB_PROJECT_ID", "local-dis")
    monkeypatch.setenv("PUBSUB_EMULATOR_HOST", "127.0.0.1:9")
    monkeypatch.setenv("STORAGE_EMULATOR_HOST", "http://127.0.0.1:9")
    app = create_app(extra_api_routers=[mapping_suggestions.router])
    with TestClient(app) as client:
        yield client


# -- handler tests ------------------------------------------------------------------


def _set_gemini(client: TestClient, fake: _FakeSuggester) -> None:
    """Set the fake on the app the fixture built; ``TestClient.app`` is typed as the
    bare ASGI callable (no ``.state``), so narrow it to the concrete FastAPI app."""
    cast(FastAPI, client.app).state.gemini = fake


def test_handler_returns_llm_suggestions(suggest_client: TestClient, mint_token) -> None:  # type: ignore[no-untyped-def]
    _set_gemini(
        suggest_client,
        _FakeSuggester(
            (
                "llm",
                "gemini-2.5-flash",
                [
                    Suggestion(
                        source_column="qty",
                        suggested_target="quantity",
                        confidence=0.9,
                        reasoning="numeric",
                    )
                ],
            )
        ),
    )
    resp = suggest_client.post(
        "/api/v1/mapping-suggestions",
        json=_BODY,
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "llm"
    assert body["model"] == "gemini-2.5-flash"
    assert body["suggestions"][0]["suggested_target"] == "quantity"
    assert body["suggestions"][0]["reasoning"] == "numeric"


def test_handler_requires_a_token(suggest_client: TestClient) -> None:
    _set_gemini(suggest_client, _FakeSuggester(("fallback", None, [])))
    resp = suggest_client.post("/api/v1/mapping-suggestions", json=_BODY)
    assert resp.status_code == 401


def test_handler_rejects_a_non_tenant_token(suggest_client: TestClient, mint_token) -> None:  # type: ignore[no-untyped-def]
    _set_gemini(suggest_client, _FakeSuggester(("fallback", None, [])))
    resp = suggest_client.post(
        "/api/v1/mapping-suggestions",
        json=_BODY,
        headers={"Authorization": f"Bearer {mint_token(user_type='PLATFORM', tenant_id=None)}"},
    )
    assert resp.status_code == 403


def test_handler_rejects_a_malformed_profile(suggest_client: TestClient, mint_token) -> None:  # type: ignore[no-untyped-def]
    _set_gemini(suggest_client, _FakeSuggester(("fallback", None, [])))
    resp = suggest_client.post(
        "/api/v1/mapping-suggestions",
        json={"columns": []},  # min_length=1 -> 422
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422


# -- type-aware catalog selection (D90) ---------------------------------------------


class _RecordingSuggester:
    """Records the catalog the handler hands it, so the catalog SELECTION can be asserted."""

    def __init__(self) -> None:
        self.catalog = None

    async def suggest(self, columns, catalog):  # type: ignore[no-untyped-def]
        self.catalog = catalog
        return ("fallback", None, [])


def test_handler_scopes_to_the_per_type_catalog_when_template_type_is_present(
    suggest_client: TestClient,
    mint_token: Callable[..., str],
) -> None:
    # A valid template_type selects THAT type's per-type catalog (snapshot included).
    fake = _RecordingSuggester()
    cast(FastAPI, suggest_client.app).state.gemini = fake
    resp = suggest_client.post(
        "/api/v1/mapping-suggestions",
        json={**_BODY, "template_type": "snapshot"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    # the exact per-type catalog object the lifespan built for snapshot was passed through
    assert fake.catalog is cast(FastAPI, suggest_client.app).state.field_catalogs["snapshot"]


def test_handler_falls_back_to_the_union_catalog_when_template_type_is_absent(
    suggest_client: TestClient,
    mint_token: Callable[..., str],
) -> None:
    # No template_type -> today's sales+inventory_change union (the /upload flow is unchanged).
    fake = _RecordingSuggester()
    cast(FastAPI, suggest_client.app).state.gemini = fake
    resp = suggest_client.post(
        "/api/v1/mapping-suggestions",
        json=_BODY,
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200
    assert fake.catalog is cast(FastAPI, suggest_client.app).state.field_catalog


def test_handler_400s_on_an_invalid_template_type(suggest_client: TestClient, mint_token) -> None:  # type: ignore[no-untyped-def]
    _set_gemini(suggest_client, _FakeSuggester(("fallback", None, [])))
    resp = suggest_client.post(
        "/api/v1/mapping-suggestions",
        json={**_BODY, "template_type": "not_a_type"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 400
    assert resp.json()["error"]["code"] == "invalid_template_type"


# -- GeminiSuggester tests ----------------------------------------------------------

_COLUMNS = [ColumnProfile(name="qty", inferred_datatype="integer", null_pct=0.0, sample_values=["1"])]


def test_suggester_falls_back_when_no_key() -> None:
    source, model, suggestions = anyio.run(GeminiSuggester(None, None).suggest, _COLUMNS, CATALOG)
    assert source == "fallback"
    assert model is None
    assert len(suggestions) == 1
    assert suggestions[0].suggested_target in CATALOG_KEYS


def test_suggester_parses_a_clean_llm_response() -> None:
    suggester = GeminiSuggester("a-project", "a-location")
    suggester._call_model = lambda prompt: json.dumps(  # type: ignore[method-assign]
        {
            "suggestions": [
                {
                    "source_column": "qty",
                    "suggested_target": "quantity",
                    "confidence": 0.82,
                    "reasoning": "integer counts",
                    "alternatives": ["unit_sale_price"],
                }
            ]
        }
    )
    source, model, suggestions = anyio.run(suggester.suggest, _COLUMNS, CATALOG)
    assert source == "llm"
    assert model == "gemini-2.5-flash"
    assert suggestions[0].suggested_target == "quantity"
    assert suggestions[0].reasoning == "integer counts"
    assert suggestions[0].alternatives == ["unit_sale_price"]


def test_suggester_nulls_a_non_catalog_target_and_drops_invented_alternatives() -> None:
    suggester = GeminiSuggester("a-project", "a-location")
    suggester._call_model = lambda prompt: json.dumps(  # type: ignore[method-assign]
        {
            "suggestions": [
                {
                    "source_column": "qty",
                    "suggested_target": "totally_made_up_field",
                    "confidence": 0.99,
                    "alternatives": ["also_fake", "quantity"],
                }
            ]
        }
    )
    source, _model, suggestions = anyio.run(suggester.suggest, _COLUMNS, CATALOG)
    assert source == "llm"
    # GUARDRAIL: invented target nulled; only the real catalog key survives in alternatives.
    assert suggestions[0].suggested_target is None
    assert suggestions[0].alternatives == ["quantity"]


def test_suggester_falls_back_when_the_model_errors() -> None:
    suggester = GeminiSuggester("a-project", "a-location")

    def _boom(prompt: str) -> str:
        raise RuntimeError("model exploded")

    suggester._call_model = _boom  # type: ignore[method-assign]
    source, model, suggestions = anyio.run(suggester.suggest, _COLUMNS, CATALOG)
    assert source == "fallback"
    assert model is None
    assert suggestions[0].suggested_target in CATALOG_KEYS


# -- Slice 34a: defaults, deadline, client reuse (criteria 2, 4, 5) -----------------


def test_suggester_defaults_disable_thinking_and_set_the_deadline() -> None:
    # Criterion 2: with no model/timeout/thinking passed (env unset -> None -> default),
    # thinking is disabled and the SDK deadline is 20s. Evidence from state/config, not a call.
    suggester = GeminiSuggester("a-project", "a-location")
    assert suggester._thinking_budget == 0
    assert suggester._timeout_ms() == 20000
    generation_config = suggester._generation_config()
    assert generation_config.response_mime_type == "application/json"
    assert generation_config.thinking_config is not None
    assert generation_config.thinking_config.thinking_budget == 0


def test_suggester_honours_overridden_knobs() -> None:
    # A set budget/timeout flows through to the generation config and the ms conversion.
    suggester = GeminiSuggester("a-project", "a-location", timeout_s=12.5, thinking_budget=256)
    assert suggester._timeout_ms() == 12500  # seconds -> ms, one conversion
    assert suggester._generation_config().thinking_config.thinking_budget == 256


def test_suggester_falls_back_on_a_deadline_timeout() -> None:
    # Criterion 4: an over-budget call surfaces as a timeout at the seam; suggest() degrades to
    # the mechanical fallback rather than hanging or raising. (The real deadline is enforced by
    # the SDK HttpOptions timeout; the seam stands in for it here.)
    suggester = GeminiSuggester("a-project", "a-location")

    def _timeout(prompt: str) -> str:
        raise TimeoutError("deadline exceeded")

    suggester._call_model = _timeout  # type: ignore[method-assign]
    source, model, suggestions = anyio.run(suggester.suggest, _COLUMNS, CATALOG)
    assert source == "fallback"
    assert model is None
    assert suggestions[0].suggested_target in CATALOG_KEYS


def test_suggester_builds_the_client_once_and_reuses_it() -> None:
    # Criterion 5: the genai.Client is constructed once per process and reused; the build seam
    # is invoked exactly once across repeated calls, and the cached object is returned each time.
    suggester = GeminiSuggester("a-project", "a-location")
    sentinel = object()
    calls = 0

    def _build() -> object:
        nonlocal calls
        calls += 1
        return sentinel

    suggester._build_client = _build  # type: ignore[method-assign]
    first = suggester._get_client()
    second = suggester._get_client()
    assert calls == 1
    assert first is sentinel
    assert second is sentinel
    assert suggester._client is sentinel


def test_call_model_wires_deadline_and_thinking_into_the_real_sdk_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Criteria 2/5 end-to-end (closes the helpers-in-isolation blind spot): drive the REAL
    # _call_model -> _build_client -> genai.Client path with a capturing fake SDK client, and
    # assert (A) the seconds->ms deadline actually reaches HttpOptions(timeout=), (B) the
    # thinking-off generation config is the one generate_content receives, and (5) the client
    # is constructed exactly once across two calls. A mutation like HttpOptions(timeout=_timeout_s)
    # or an inline config without thinking_config would fail here, where the helper tests would not.
    import google.genai as genai

    captured: dict[str, object] = {}
    constructions = {"n": 0}

    class _FakeModels:
        def generate_content(self, *, model, contents, config):  # type: ignore[no-untyped-def]
            captured["model"] = model
            captured["contents"] = contents
            captured["config"] = config
            return type("R", (), {"text": '{"suggestions": []}'})()

    class _FakeClient:
        def __init__(self, **kwargs):  # type: ignore[no-untyped-def]
            constructions["n"] += 1
            captured["client_kwargs"] = kwargs
            self.models = _FakeModels()

    monkeypatch.setattr(genai, "Client", _FakeClient)
    suggester = GeminiSuggester("a-project", "a-location")  # defaults: 20s deadline, budget 0

    out1 = suggester._call_model('{"columns": []}')
    out2 = suggester._call_model('{"columns": []}')

    assert out1 == '{"suggestions": []}'
    assert out2 == '{"suggestions": []}'
    client_kwargs = cast(Any, captured["client_kwargs"])
    # (A) the ms deadline landed in the ACTUAL HttpOptions passed to genai.Client.
    assert client_kwargs["http_options"].timeout == 20000
    assert client_kwargs["vertexai"] is True
    # (B) the config generate_content received disables thinking and asks for JSON.
    config = cast(Any, captured["config"])
    assert config.thinking_config.thinking_budget == 0
    assert config.response_mime_type == "application/json"
    assert captured["model"] == "gemini-2.5-flash"
    # (5) built once across two real _call_model calls.
    assert constructions["n"] == 1


# -- Slice 34a: elapsed_ms on the response (criterion 9) ----------------------------


class _SlowSuggester:
    """A suggester whose suggest() takes a measurable moment, to prove elapsed_ms is real."""

    def __init__(self, result: tuple[str, str | None, list[Suggestion]]) -> None:
        self._result = result

    async def suggest(self, columns, catalog):  # type: ignore[no-untyped-def]
        await anyio.sleep(0.02)
        return self._result


def test_handler_reports_elapsed_ms_on_the_llm_path(suggest_client: TestClient, mint_token) -> None:  # type: ignore[no-untyped-def]
    cast(FastAPI, suggest_client.app).state.gemini = _SlowSuggester(
        (
            "llm",
            "gemini-2.5-flash",
            [Suggestion(source_column="qty", suggested_target="quantity", confidence=0.9)],
        )
    )
    resp = suggest_client.post(
        "/api/v1/mapping-suggestions", json=_BODY, headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200
    elapsed = resp.json()["elapsed_ms"]
    assert isinstance(elapsed, int)
    assert elapsed >= 10  # the ~20ms suggest() was measured, not reported as ~0


def test_handler_reports_elapsed_ms_on_the_fallback_path(suggest_client: TestClient, mint_token) -> None:  # type: ignore[no-untyped-def]
    cast(FastAPI, suggest_client.app).state.gemini = _SlowSuggester(("fallback", None, []))
    resp = suggest_client.post(
        "/api/v1/mapping-suggestions", json=_BODY, headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200
    elapsed = resp.json()["elapsed_ms"]
    assert isinstance(elapsed, int)
    assert elapsed >= 10
