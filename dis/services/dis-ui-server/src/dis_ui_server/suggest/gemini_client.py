"""The Gemini-backed mapping suggester, with the mechanical fallback built in.

Auth is Vertex AI / GCP-native: the suggester takes (project, location), constructs
``genai.Client(vertexai=True, project=..., location=...)``, and authenticates via Application
Default Credentials (the Cloud Run service account). There is no API key string.

Optional SA impersonation: when ``impersonate_sa`` is set, the Vertex calls (and ONLY those)
impersonate that service account (gemini-dis) via short-lived
``google.auth.impersonated_credentials`` minted from the ambient ADC; the service still runs as
its own SA for everything else. Unset -> the ambient ADC is used directly.

``GeminiSuggester.suggest`` returns ``(source, model, suggestions)``:

- project/location unset, or any model error/timeout/parse failure -> the mechanical
  ``fallback_matcher`` result with ``source="fallback"``. The frontend must always receive
  suggestions, so missing config or LLM trouble degrades, never raises.
- Vertex configured and a clean structured response -> ``source="llm"``, with every
  ``suggested_target`` and alternative VALIDATED against the catalog key set (the
  model cannot invent a field; invalid targets are nulled / dropped).

The blocking google-genai call runs off the event loop via ``anyio.to_thread``.
The request DEADLINE is enforced at the SDK level via ``HttpOptions(timeout=...)``
(milliseconds) — NOT an outer ``anyio.fail_after``, which is inert against a
non-cancellable worker thread (Slice 34a / D-b). The ``genai.Client`` is built ONCE
per process and reused (Slice 34a): construction stays lazy (first call, in the
worker thread) so startup does no I/O, and the SDK auto-refreshes credentials on the
long-lived client. The google-genai import is LAZY (inside the client seam) so this
module loads without the package; only the real LLM path needs it. ``_call_model`` is
the single network seam tests override.
"""

from __future__ import annotations

import json
import threading
from typing import Any

import anyio

from dis_core.logging import get_logger
from dis_ui_server.config import SERVICE_NAME
from dis_ui_server.schemas.mapping_fields import TemplateMappingField
from dis_ui_server.schemas.mapping_suggestions import ColumnProfile, Suggestion, SuggestionSource
from dis_ui_server.suggest.fallback_matcher import match_columns

_log = get_logger(SERVICE_NAME)

# Built-in defaults (Slice 34a): the ONE place the fast-path values live. Config passes None
# when the env var is unset, and the constructor resolves None to these.
_DEFAULT_MODEL = "gemini-2.5-flash"
_DEFAULT_TIMEOUT_S = 20.0  # SDK request deadline (seconds); a stall guard above valid latency.
_DEFAULT_THINKING_BUDGET = 0  # 0 = thinking DISABLED (the latency fix); -1 = automatic.
# The scope Vertex calls need; also the impersonation target scope.
_CLOUD_PLATFORM_SCOPE = "https://www.googleapis.com/auth/cloud-platform"


class GeminiSuggester:
    """Produces per-column mapping suggestions via Gemini, falling back mechanically."""

    def __init__(
        self,
        project: str | None,
        location: str | None,
        *,
        impersonate_sa: str | None = None,
        model: str | None = None,
        timeout_s: float | None = None,
        thinking_budget: int | None = None,
    ) -> None:
        # Vertex AI (GCP-native) auth: no key string. project + location select the Vertex
        # backend; credentials come from Application Default Credentials (the Cloud Run service
        # account), not from a configured secret. Both unset -> mechanical fallback.
        # impersonate_sa (optional): impersonate this SA for the Vertex calls only; unset ->
        # ambient ADC used directly.
        # model/timeout_s/thinking_budget: None (env unset) -> the built-in default constant.
        self._project = project
        self._location = location
        self._impersonate_sa = impersonate_sa
        self._model = model or _DEFAULT_MODEL
        self._timeout_s = timeout_s if timeout_s is not None else _DEFAULT_TIMEOUT_S
        self._thinking_budget = thinking_budget if thinking_budget is not None else _DEFAULT_THINKING_BUDGET
        # Built ONCE per process on the first LLM call (below), then reused; the lock makes the
        # first-call construction race-free across concurrent worker threads. Typed Any to keep
        # the google-genai import lazy (this module must load without the package).
        self._client: Any = None
        self._client_lock = threading.Lock()

    async def suggest(
        self,
        columns: list[ColumnProfile],
        catalog: list[TemplateMappingField],
    ) -> tuple[SuggestionSource, str | None, list[Suggestion]]:
        """Return (source, model, suggestions); never raises on LLM trouble."""
        if not self._project or not self._location:
            return ("fallback", None, match_columns(columns, catalog))
        try:
            prompt = self._build_prompt(columns, catalog)
            # The deadline is enforced INSIDE the SDK call via HttpOptions(timeout=...); the old
            # anyio.fail_after wrapper was inert against this non-cancellable worker thread
            # (Slice 34a / D-b) and is removed. A deadline hit surfaces as an SDK timeout error,
            # caught below and degraded to the mechanical fallback.
            text = await anyio.to_thread.run_sync(self._call_model, prompt)
            suggestions = self._parse_and_validate(text, columns, catalog)
            return ("llm", self._model, suggestions)
        except Exception as exc:  # timeout, transport, parse, anything: degrade
            _log.bind(stage="mapping_suggestions", error=type(exc).__name__).warning(
                "gemini suggestion failed; using mechanical fallback"
            )
            return ("fallback", None, match_columns(columns, catalog))

    # -- the network seam (lazy import; tests override _call_model or _build_client) --

    def _call_model(self, prompt: str) -> str:
        """Blocking Gemini call returning the raw JSON text. Reuses the per-process client.

        The generate_content + structured-output (response_mime_type) call is identical for
        the ADC and impersonation branches (they differ only in the client's credentials),
        so the prompt/parse/validation logic is unchanged. Thinking is set from the configured
        budget (default 0 = disabled).
        """
        client = self._get_client()
        response = client.models.generate_content(
            model=self._model,
            contents=prompt,
            config=self._generation_config(),
        )
        return response.text or ""

    def _generation_config(self) -> Any:
        """The per-call generation config: JSON-only output with thinking set to the configured
        budget (default 0 = disabled). Lazy-imports the SDK; a directly testable pure helper."""
        from google.genai import types

        return types.GenerateContentConfig(
            response_mime_type="application/json",
            thinking_config=types.ThinkingConfig(thinking_budget=self._thinking_budget),
        )

    def _get_client(self) -> Any:
        """Return the process-wide ``genai.Client``, building it once (race-free) on first use.

        Lazy so startup does no I/O; reused thereafter (the SDK auto-refreshes credentials on
        the long-lived client). Double-checked lock: concurrent first calls build exactly one.
        """
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = self._build_client()
        return self._client

    def _build_client(self) -> Any:
        """Construct the Vertex ``genai.Client`` with the SDK request deadline. Lazy-imports
        the SDK. ``vertexai=True`` selects the Vertex backend with the given project + location.
        With ``impersonate_sa`` set, the client uses short-lived impersonated credentials for
        that SA (minted from the ambient ADC via google.auth); otherwise the ambient ADC (the
        Cloud Run service account) is used directly. No API key."""
        import google.genai as genai
        from google.genai import types

        http_options = types.HttpOptions(timeout=self._timeout_ms())
        if self._impersonate_sa:
            import google.auth
            from google.auth import impersonated_credentials

            source_credentials, _ = google.auth.default(scopes=[_CLOUD_PLATFORM_SCOPE])
            # google.auth's impersonated_credentials.Credentials is not type-annotated, so the
            # strict-typed call is flagged; the args are exactly the documented Vertex pattern.
            credentials = impersonated_credentials.Credentials(  # type: ignore[no-untyped-call]
                source_credentials=source_credentials,
                target_principal=self._impersonate_sa,
                target_scopes=[_CLOUD_PLATFORM_SCOPE],
            )
            return genai.Client(
                vertexai=True,
                project=self._project,
                location=self._location,
                credentials=credentials,
                http_options=http_options,
            )
        return genai.Client(
            vertexai=True, project=self._project, location=self._location, http_options=http_options
        )

    def _timeout_ms(self) -> int:
        """The configured request deadline in milliseconds (the SDK ``HttpOptions`` unit)."""
        return round(self._timeout_s * 1000)

    # -- pure helpers (directly testable) ------------------------------------------

    def _build_prompt(self, columns: list[ColumnProfile], catalog: list[TemplateMappingField]) -> str:
        """Compose the prompt: the catalog is the CLOSED target set, JSON out only."""
        targets = [
            {
                "key": field.key,
                "display_name": field.display_name,
                "datatype": field.datatype,
                "section": field.section,
                "description": field.description,
            }
            for field in catalog
        ]
        profile = [
            {
                "source_column": column.name,
                "inferred_datatype": column.inferred_datatype,
                "null_pct": column.null_pct,
                "sample_values": column.sample_values,
            }
            for column in columns
        ]
        instructions = (
            "You map source CSV columns to canonical retail fields. For EACH source "
            "column, choose the single best target from the allowed targets, or null if "
            "no target fits. You MUST only use a target 'key' from the allowed list; "
            "never invent a field. Return ONLY JSON of the shape: "
            '{"suggestions": [{"source_column": str, "suggested_target": str or null, '
            '"confidence": number 0..1, "reasoning": short string, '
            '"alternatives": [target key, ...]}]}.'
        )
        return json.dumps(
            {
                "instructions": instructions,
                "allowed_targets": targets,
                "columns": profile,
            }
        )

    def _parse_and_validate(
        self,
        text: str,
        columns: list[ColumnProfile],
        catalog: list[TemplateMappingField],
    ) -> list[Suggestion]:
        """Parse the model JSON and constrain every target to a real catalog key."""
        valid_keys = {field.key for field in catalog}
        parsed = json.loads(text)
        raw_items = parsed.get("suggestions", []) if isinstance(parsed, dict) else []
        by_column: dict[str, dict[str, Any]] = {}
        for item in raw_items:
            if isinstance(item, dict) and isinstance(item.get("source_column"), str):
                by_column[item["source_column"]] = item

        suggestions: list[Suggestion] = []
        for column in columns:
            item = by_column.get(column.name, {})
            target = item.get("suggested_target")
            # GUARDRAIL: only a real catalog key survives; anything else -> null.
            if not isinstance(target, str) or target not in valid_keys:
                target = None
            confidence = item.get("confidence", 0.0)
            confidence = float(confidence) if isinstance(confidence, (int, float)) else 0.0
            confidence = min(1.0, max(0.0, confidence))
            reasoning = item.get("reasoning")
            reasoning = reasoning if isinstance(reasoning, str) and reasoning else None
            raw_alts = item.get("alternatives")
            alternatives: list[str] | None = None
            if isinstance(raw_alts, list):
                alts = [a for a in raw_alts if isinstance(a, str) and a in valid_keys]
                alternatives = alts or None
            suggestions.append(
                Suggestion(
                    source_column=column.name,
                    suggested_target=target,
                    confidence=confidence,
                    reasoning=reasoning,
                    alternatives=alternatives,
                )
            )
        return suggestions
