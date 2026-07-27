"""HTTP server entrypoint: app factory, lifespan, router mounting.

Startup split (test-pinned, the liveness/readiness foundation):

- MISSING required config (``POSTGRES_URL``) fails fast inside the lifespan —
  startup aborts and the platform crashloops, the correct signal for
  misconfiguration.
- PRESENT-but-unreachable database does NOT block startup: ``create_rls_engine``
  is lazy (no connection until first execute), the lifespan performs no
  connectivity check, so ``/healthz`` serves 200 while ``/readyz`` degrades to
  503 where the first real connect happens.

The lifespan owns the engine (dis-rls CLAUDE.md: caller owns the engine, no
hidden global) and disposes it on shutdown.

Run: ``uvicorn dis_ui_server.main:app`` (the Dockerfile CMD).
"""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from dis_audit import AuditBackend, select_writer
from dis_core.logging import configure_logging, get_logger
from dis_storage import StorageClient
from dis_ui_server.api import api_router
from dis_ui_server.audit import UiAudit
from dis_ui_server.auth.auth0 import Auth0Verifier
from dis_ui_server.auth.verifier import StubVerifier
from dis_ui_server.catalog import build_field_catalogs
from dis_ui_server.config import (
    API_PREFIX,
    SERVICE_NAME,
    UiServerConfig,
    cors_allowed_origins_from_env,
)
from dis_ui_server.db import create_engine_from_config
from dis_ui_server.errors_http import register_error_handlers
from dis_ui_server.handlers import health
from dis_ui_server.publisher import PubsubPublisher
from dis_ui_server.suggest.gemini_client import GeminiSuggester
from thalamus_square_oauth import (
    SQUARE_READ_SCOPES,
    GoogleSecretBackend,
    SquareOAuthClient,
    SquareTokenVault,
)

_log = get_logger(SERVICE_NAME)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    config = UiServerConfig.from_env()  # raises on missing required env
    engine = create_engine_from_config(config)  # lazy: no connection yet
    app.state.config = config
    app.state.engine = engine
    # Token verifier, mode-selected once per process (mirrors Customer Master's
    # STUB|AUTH0 auth_client). STUB (default) wraps the HS256 dev stub; AUTH0
    # builds the RS256/JWKS verifier holding a cached PyJWKClient (no network I/O
    # at construction; the first verify does the JWKS fetch). scope.py reads this
    # off app.state and calls .verify; both modes yield the identical Identity.
    if config.auth_mode == "AUTH0":
        app.state.verifier = Auth0Verifier(
            jwks_url=config.auth0_jwks_url,
            issuer=config.jwt_issuer,
            audience=config.jwt_audience,
        )
    else:
        app.state.verifier = StubVerifier()
    # Slice 8 upload dependencies — all construction-lazy like the engine (no
    # network I/O until first use), so the liveness/readiness split holds: a
    # missing env var crashloops here, an unreachable backend degrades later.
    # PubsubPublisher is emulator-or-ambient (slice 40a): the emulator when
    # PUBSUB_EMULATOR_HOST is set, real Pub/Sub via ambient credentials when not.
    # Tests override these state entries with fakes after startup.
    app.state.storage = StorageClient(bucket=config.gcs_bucket_bronze)
    app.state.publisher = PubsubPublisher(project_id=config.pubsub_project_id)
    app.state.audit = UiAudit(select_writer(AuditBackend.POSTGRES, engine=engine))
    # Built once per process (inputs are code constants; no DB, no tenant). A
    # label-vs-derivation drift raises FieldCatalogDriftError HERE, aborting
    # startup — crashloop is the correct signal, never a half-true catalog.
    app.state.field_catalogs = build_field_catalogs()
    # The mapping-suggestion feature (out of 14d scope) keeps its flat event field
    # universe; built from the same drift-guarded per-type catalogs.
    app.state.field_catalog = app.state.field_catalogs["sales"] + app.state.field_catalogs["inventory_change"]
    # Mapping-suggestion producer (Vertex AI / GCP-native auth, ADC from the Cloud Run service
    # account; no API key). GEMINI_VERTEX_PROJECT/LOCATION are OPTIONAL: both unset -> the
    # suggester returns the mechanical fallback (no crashloop). Construction is I/O-free (the
    # google-genai client is built ONCE on the first LLM call and reused for the process
    # lifetime), and it holds no resource to dispose, so there is no shutdown step for it. The
    # operational knobs (model/timeout/thinking budget) come from config; None -> the
    # suggester's built-in default (gemini-2.5-flash, 20s SDK deadline, thinking disabled).
    app.state.gemini = GeminiSuggester(
        project=config.gemini_vertex_project,
        location=config.gemini_vertex_location,
        impersonate_sa=config.gemini_impersonate_sa,
        model=config.gemini_model,
        timeout_s=config.gemini_timeout_s,
        thinking_budget=config.gemini_thinking_budget,
    )
    # The OAuth state-signing key is SHARED across connectors, so it is published
    # UNCONDITIONALLY, outside any vendor branch. Publishing a shared primitive inside the
    # Square branch would mean an unconfigured Square silently disabled every other
    # vendor's connect flow.
    app.state.oauth_state_key = config.oauth_state_key
    # Square OAuth connect (S2), optional at boot (like the GEMINI_* config): built once when
    # fully configured, else left None so the OAuth endpoints 503. Construction is I/O-free
    # (httpx.Client build; the Secret Manager client is credential-lazy), so an unreachable
    # backend never blocks startup. Tests override these with fakes after startup.
    if config.square_oauth_configured:
        # square_oauth_configured guarantees these four are set; assert narrows for typing.
        assert config.square_client_id is not None
        assert config.square_app_secret is not None
        assert config.square_oauth_redirect_uri is not None
        assert config.square_oauth_state_key is not None
        secrets_project = config.square_secrets_project_id or config.pubsub_project_id
        app.state.square_oauth_client = SquareOAuthClient(
            base_url=config.square_oauth_base_url,
            client_id=config.square_client_id,
            client_secret=config.square_app_secret,
            redirect_uri=config.square_oauth_redirect_uri,
            scopes=SQUARE_READ_SCOPES,
            environment=config.square_oauth_environment,
        )
        app.state.square_token_vault = SquareTokenVault(GoogleSecretBackend(project_id=secrets_project))
        app.state.square_oauth_state_key = config.square_oauth_state_key
    else:
        app.state.square_oauth_client = None
        app.state.square_token_vault = None
        app.state.square_oauth_state_key = None
    _log.bind(stage="startup").info("dis-ui-server started")
    try:
        yield
    finally:
        await engine.dispose()
        _log.bind(stage="shutdown").info("dis-ui-server stopped")


def create_app(extra_api_routers: Sequence[APIRouter] = ()) -> FastAPI:
    """Build the application.

    ``extra_api_routers`` is a TEST seam: tests mount probe routes under the
    ``/api/v1`` prefix through the same mechanism production handlers will use,
    proving the prefix wiring without mutating module state. Production callers
    use the module-level ``app`` and pass nothing.
    """
    configure_logging()  # idempotent
    app = FastAPI(title=SERVICE_NAME, lifespan=_lifespan)
    # CORS for the browser-served dis-ui SPA (Slice 14c). Explicit origins only
    # (no wildcard exists anywhere); allow_credentials=False because auth is the
    # Authorization: Bearer header, never cookies (dis-ui client.ts + contract
    # §2.1 "No cookies, no CSRF surface") — the Authorization header itself is
    # granted via allow_headers. Pure ASGI middleware: it wraps the §2.3 error
    # envelopes too (a browser can read a 4xx body), and adds nothing when no
    # Origin header is present (probes and curl traffic are byte-unchanged).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(cors_allowed_origins_from_env()),
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    register_error_handlers(app)
    app.include_router(health.router)  # probes at the root, per infra convention
    app.include_router(api_router)  # the /api/v1 base for all UI data endpoints
    for router in extra_api_routers:
        # Same prefix constant, same include mechanism, per-app (the shared
        # api_router is never mutated, so test routes cannot leak across apps).
        app.include_router(router, prefix=API_PREFIX)
    return app


app = create_app()
