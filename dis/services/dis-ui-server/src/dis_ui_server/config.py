"""Environment-resolved configuration for the UI server.

Required env (no silent default for a required value — a missing one raises
``DisError``; this service deliberately defines no service-specific
config-error class):

- ``POSTGRES_URL`` — the DIS connection (``ithina_dis_user``). Reused by
  ``dis-rls`` ``create_rls_engine``, which positively asserts
  ``current_database()=='ithina_dis_db'`` and a NOSUPERUSER/NOBYPASSRLS role
  (DIS on 5433, never Customer Master).
- ``GCS_BUCKET_BRONZE`` — the bronze bucket the CSV upload writes to (the same
  env name the csv-ingest-worker cross-checks the published ``gcs_uri``
  against, so producer and consumer cannot drift).
- ``PUBSUB_PROJECT_ID`` — the Pub/Sub project for the ``csv.received`` publish.

OPTIONAL env (NOT in the required-or-crashloop set):

- ``GEMINI_VERTEX_PROJECT`` / ``GEMINI_VERTEX_LOCATION``: the Vertex AI project and
  location for the mapping-suggestion endpoint. Auth is GCP-native (Application
  Default Credentials from the Cloud Run service account), NOT an API key. BOTH
  UNSET is a normal state: the suggester falls back to the mechanical matcher, so
  missing config must NEVER abort startup (they are read with no raise).
- ``GEMINI_IMPERSONATE_SA``: optional service-account email (gemini-dis) to
  IMPERSONATE for the Vertex calls only. When set (with project+location), the
  suggester impersonates this SA via short-lived credentials; the service still
  runs as its own SA for everything else. Unset -> the ambient ADC (the Cloud Run
  service account) is used directly. Read with no raise.
- ``GEMINI_MODEL`` / ``GEMINI_TIMEOUT_S`` / ``GEMINI_THINKING_BUDGET``: the
  operational knobs for the suggester. UNSET means the suggester's built-in default
  (``gemini-2.5-flash``; ``20.0`` seconds; thinking budget ``0`` = disabled). Unlike the
  three ``GEMINI_VERTEX_*``/``_IMPERSONATE_SA`` reads above (which are silently None on
  missing/empty), these three FAIL LOUDLY: a set-but-empty or unparseable value raises
  ``DisError`` at startup NAMING the variable (a bad tunable is a misconfiguration, not a
  silent fallback). ``GEMINI_TIMEOUT_S`` is seconds (float, > 0), converted to the SDK's
  milliseconds once at construction; it is a request DEADLINE (a stall guard), not the
  latency mechanism. ``GEMINI_THINKING_BUDGET`` is an int token budget where ``0`` disables
  thinking, ``-1`` is automatic, and a positive value caps it (per the google-genai SDK);
  values below ``-1`` are rejected.

Resolution happens inside the app lifespan, NOT at import time: a missing
required value aborts startup loudly (crashloop is the correct signal for
misconfiguration), while a present-but-unreachable database must NOT block
startup — the engine is lazy and the first connect happens in ``/readyz``,
which degrades to 503. That split is the liveness/readiness foundation and is
test-pinned.

The dev-stub verifier parameters are NOT config: they are contract-pinned
constants in ``auth/verifier.py`` (byte-identical to the UI's ``/dev/login``
stub so dev tokens round-trip; env-overridable values would invite drift).
"""

from __future__ import annotations

import os
from dataclasses import dataclass

from sqlalchemy.engine import make_url
from sqlalchemy.exc import ArgumentError

from dis_core.errors import DisError
from dis_core.pubsub_names import resolve_pubsub_name

_POSTGRES_URL = "POSTGRES_URL"
_CORS_ALLOWED_ORIGINS = "CORS_ALLOWED_ORIGINS"
_GCS_BUCKET_BRONZE = "GCS_BUCKET_BRONZE"
_PUBSUB_PROJECT_ID = "PUBSUB_PROJECT_ID"
# Auth mode + real-Auth0 verify config. DIS_AUTH_MODE selects the
# token verifier: AUTH0 (the DEFAULT; the RS256/JWKS verifier) or STUB (the HS256
# dev stub, which additionally requires a loopback database, see
# _refuse_stub_against_a_remote_database). JWT_ISSUER / JWT_AUDIENCE are REQUIRED
# only in AUTH0 mode; AUTH0_JWKS_URL is optional and derived from the issuer when
# unset (the Auth0 convention, mirroring Customer Master).
_DIS_AUTH_MODE = "DIS_AUTH_MODE"
# The explicit local/test opt-in that STUB additionally requires (P1-SEC-001). See
# _refuse_stub_without_explicit_local_permission.
_DIS_ALLOW_STUB_AUTH = "DIS_ALLOW_STUB_AUTH"
_JWT_ISSUER = "JWT_ISSUER"
_JWT_AUDIENCE = "JWT_AUDIENCE"
_AUTH0_JWKS_URL = "AUTH0_JWKS_URL"
# OPTIONAL (Vertex AI): both unset -> mechanical fallback, never crashloop.
_GEMINI_VERTEX_PROJECT = "GEMINI_VERTEX_PROJECT"
_GEMINI_VERTEX_LOCATION = "GEMINI_VERTEX_LOCATION"
# OPTIONAL: SA to impersonate for Vertex calls only (unset -> ambient ADC).
_GEMINI_IMPERSONATE_SA = "GEMINI_IMPERSONATE_SA"
# OPTIONAL operational knobs: unset -> the suggester's built-in default;
# set-but-empty or unparseable -> raise DisError naming the var (fail loud, not silent).
_GEMINI_MODEL = "GEMINI_MODEL"
_GEMINI_TIMEOUT_S = "GEMINI_TIMEOUT_S"
_GEMINI_THINKING_BUDGET = "GEMINI_THINKING_BUDGET"
# OPTIONAL (Square OAuth): the connect endpoints. ALL optional at boot (like the
# GEMINI_* knobs) — unset leaves the OAuth endpoints returning a fail-loud 503 while the
# rest of the BFF runs unchanged. SQUARE_APP_SECRET + STATE_SIGNING_KEY are secret-backed
# env (Cloud Run secret_key_ref); the rest are plain. The per-tenant token secrets are
# created at runtime by the callback, not env.
_SQUARE_CLIENT_ID = "SQUARE_CLIENT_ID"
_SQUARE_APP_SECRET = "SQUARE_APP_SECRET"
_SQUARE_OAUTH_BASE_URL = "SQUARE_OAUTH_BASE_URL"
_SQUARE_OAUTH_REDIRECT_URI = "SQUARE_OAUTH_REDIRECT_URI"
# SHARED ACROSS CONNECTORS, not Square-specific: the HS256 key signing the stateless OAuth
# `state` token. One key, one secret, every vendor. Read once into `oauth_state_key`.
_OAUTH_STATE_KEY = "STATE_SIGNING_KEY"
_SQUARE_SECRETS_PROJECT_ID = "SQUARE_SECRETS_PROJECT_ID"
# OPTIONAL (Clover OAuth), same posture as Square's: unset leaves the Clover connect
# endpoints on a fail-loud 503 while the rest of the BFF runs unchanged. CLOVER_APP_SECRET
# is secret-backed env; the rest are plain. The state key is SHARED (see _OAUTH_STATE_KEY).
_CLOVER_CLIENT_ID = "CLOVER_CLIENT_ID"
_CLOVER_APP_SECRET = "CLOVER_APP_SECRET"
_CLOVER_OAUTH_BASE_URL = "CLOVER_OAUTH_BASE_URL"
_CLOVER_OAUTH_REDIRECT_URI = "CLOVER_OAUTH_REDIRECT_URI"
_CLOVER_SECRETS_PROJECT_ID = "CLOVER_SECRETS_PROJECT_ID"

SERVICE_NAME = "dis-ui-server"

# Default Square OAuth host when SQUARE_OAUTH_BASE_URL is unset (sandbox). The environment
# stamped onto stored token sets is derived from this host.
SQUARE_SANDBOX_OAUTH_BASE_URL = "https://connect.squareupsandbox.com"

# Default Clover OAuth host when CLOVER_OAUTH_BASE_URL is unset. Clover hosts are per-REGION
# as well as per-environment, so a production deploy always sets this explicitly.
CLOVER_SANDBOX_OAUTH_BASE_URL = "https://sandbox.dev.clover.com"

# The CSV-upload publish target. The contract name is
# "csv.received" and remains the default, so local dev (provisioned by
# tools/local/create_topics.py, no env set) is unchanged. Deployment overrides via
# CSV_RECEIVED_TOPIC with the actually-provisioned short name (terraform sources it
# from the pubsub module output, so app and infra cannot drift).
CSV_RECEIVED_TOPIC = resolve_pubsub_name("CSV_RECEIVED_TOPIC", "csv.received")

# The upload ceiling (a design value, not deployment config): 10 MB removes
# the large-file case for direct-to-GCS. Enforced MID-STREAM in upload_stream.py
# (the spoofable Content-Length early-reject is only the cheap first check).
CSV_UPLOAD_MAX_FILE_BYTES = 10 * 1024 * 1024

# The raw-body ceiling = the file limit + an allowance for multipart framing
# (boundaries, part headers, the small template_id/store_code fields). Anything
# past this is rejected mid-stream regardless of how the parts are arranged.
CSV_UPLOAD_BODY_CEILING_BYTES = CSV_UPLOAD_MAX_FILE_BYTES + 64 * 1024

# The browser-served dis-ui SPA's dev origin (Vite's default dev-server port,
# http://localhost:5173). NEVER a wildcard: a
# permissive dev posture must not be expressible by default; deployed origins
# are set per environment via CORS_ALLOWED_ORIGINS.
_DEFAULT_CORS_ORIGINS: tuple[str, ...] = ("http://localhost:5173",)

# Every UI data endpoint mounts under this prefix (durable invariant); health
# probes stay at the root. The contract's relative /v1/<group>/<resource>
# paths are unchanged — only the deployed base shifts, and the frontend's
# fetch base must agree.
API_PREFIX = "/api/v1"


def _optional_str_env(name: str) -> str | None:
    """An optional string env var: unset -> None (use the default);
    set-but-empty -> raise ``DisError`` naming the var. Distinct from the silent ``or None``
    used for the ``GEMINI_VERTEX_*`` reads, whose migration to this policy is deferred."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    if not raw.strip():
        raise DisError(f"{name} is set but empty; unset it to use the default or give a value")
    return raw


def _optional_float_env(name: str) -> float | None:
    """An optional positive-float env var: unset -> None; set-but-empty/unparseable/<=0 ->
    raise ``DisError`` naming the var. The numeric-env precedent for this module."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        raise DisError(f"{name} is set but empty; unset it to use the default or give a number of seconds")
    try:
        value = float(raw)
    except ValueError:
        raise DisError(f"{name}={raw!r} is not a number; expected seconds as a float") from None
    if value <= 0:
        raise DisError(f"{name}={value} must be greater than 0 seconds")
    return value


def _optional_int_env(name: str) -> int | None:
    """An optional int env var bounded to the google-genai thinking-budget domain: unset ->
    None; set-but-empty/unparseable/< -1 -> raise ``DisError`` naming the var. The SDK defines
    only 0 (disabled), -1 (automatic), and positive budgets, so anything below -1 is invalid."""
    raw = os.environ.get(name)
    if raw is None:
        return None
    raw = raw.strip()
    if not raw:
        raise DisError(
            f"{name} is set but empty; unset it to use the default or give an integer token budget"
        )
    try:
        value = int(raw)
    except ValueError:
        raise DisError(
            f"{name}={raw!r} is not an integer; expected a token budget (0=disabled, -1=automatic)"
        ) from None
    if value < -1:
        raise DisError(f"{name}={value} is invalid; use 0 (disabled), -1 (automatic), or a positive budget")
    return value


# The only database hosts the HS256 dev stub may run against. NOT A DENYLIST: a list of
# forbidden hosts is a list somebody has to keep current, and the one it misses is the one
# that matters.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


# The only values that count as "yes, this is a sanctioned local or test process". Anything
# else - unset, empty, "0", "false", "no", a typo - is a no.
_STUB_PERMISSION_GRANTED = frozenset({"1", "true", "yes"})


def _refuse_stub_without_explicit_local_permission() -> None:
    """Refuse the HS256 dev stub unless this process was explicitly told it is local.

    =============================================================================================
    WHY THE DATABASE HOST IS NOT ENOUGH ON ITS OWN
    =============================================================================================
    _refuse_stub_against_a_remote_database asks "is the database loopback?" and treats a yes as
    evidence that the process is a developer laptop. That inference is not sound. A Cloud SQL
    Auth Proxy sidecar listens on 127.0.0.1 inside the very same container, which is the
    supported way to reach a managed database from Cloud Run - so a deployed process can answer
    "yes, loopback" while talking to production data. Database topology is a property of the
    connection, not a declaration of where the application is running.

    So locality has to be DECLARED, explicitly, by whoever starts the process. This variable is
    that declaration and nothing else sets it: it is absent from the Terraform module, absent
    from every deployment definition, and set only by local/test tooling.

    FAIL CLOSED BY DEFAULT. Absent is a refusal, so a deployment that somehow requested STUB
    crashloops rather than accepting tokens signed with a published constant. Both conditions
    are required, not either: the declaration says "local", the loopback check says "and the
    data is local too", and a forged token needs both to be wrong before it reaches real rows.
    """
    granted = (os.environ.get(_DIS_ALLOW_STUB_AUTH) or "").strip().lower()
    if granted in _STUB_PERMISSION_GRANTED:
        return
    raise DisError(
        f"{_DIS_AUTH_MODE}=STUB was requested but {_DIS_ALLOW_STUB_AUTH} is not set to an "
        f"explicit opt-in (one of: {', '.join(sorted(_STUB_PERMISSION_GRANTED))}). The HS256 "
        "dev stub accepts tokens signed with a constant that ships publicly, and its claims "
        "drive RLS, so it runs only where a human has declared the process local. A loopback "
        "database is NOT that declaration: a Cloud SQL Auth Proxy sidecar is loopback inside a "
        "deployed container. Set it in local tooling only; it must never appear in a "
        "deployment definition."
    )


def _refuse_stub_against_a_remote_database(postgres_url: str) -> None:
    """Refuse the HS256 dev stub unless the database is local. Raises, or returns None.

    =============================================================================================
    WHY THE MODE ALONE IS NOT A SUFFICIENT CONDITION
    =============================================================================================
    DIS_AUTH_MODE and POSTGRES_URL are independent values read from the same environment. An
    operator who sets STUB for a local session while POSTGRES_URL still points at staging gets a
    verifier that accepts a symmetric-signed token against real tenant data, and the stub's
    secret is a published constant. Checking the mode and stopping there would pass cleanly in
    exactly that case, which is the shape of a guard that is not one.

    So the second condition is the CONNECTION TARGET, parsed with SQLAlchemy's own make_url
    rather than a regex so this reads the same target create_rls_engine will open. Staging is a
    private IP and the Cloud SQL socket form parses to no host at all, so both are refused by
    construction rather than by a list of forbidden things.

    Same guard, same reasoning, as the one on scripts/seed_dev_data in cm-backend.

    FAIL CLOSED. A URL this cannot parse is a URL it refuses: a guard that cannot read its input
    has checked nothing. The message names the host and never the URL, which carries a password.
    """
    try:
        host = make_url(postgres_url).host
    except (ArgumentError, ValueError) as exc:
        raise DisError(
            f"{_DIS_AUTH_MODE}=STUB was requested but {_POSTGRES_URL} could not be parsed, so "
            "this process cannot tell whether the dev stub would be accepting tokens against a "
            "local database or a real one. Refusing to start."
        ) from exc

    if host is None:
        raise DisError(
            f"{_DIS_AUTH_MODE}=STUB was requested but {_POSTGRES_URL} names no TCP host, which "
            "is the Cloud SQL socket form. The HS256 dev stub is a local-only verifier and its "
            "signing secret is a published constant; it must not run against a managed database."
        )

    if host not in _LOOPBACK_HOSTS:
        raise DisError(
            f"{_DIS_AUTH_MODE}=STUB was requested but {_POSTGRES_URL} points at {host!r}, which "
            "is not loopback. The HS256 dev stub accepts tokens signed with a published constant "
            "and its claims drive RLS, so running it against a remote database would make a "
            f"forged token a read of real tenant data. Allowed hosts: "
            f"{', '.join(sorted(_LOOPBACK_HOSTS))}."
        )


@dataclass(frozen=True)
class UiServerConfig:
    """Resolved environment profile for one server process."""

    postgres_url: str
    gcs_bucket_bronze: str
    pubsub_project_id: str
    # Auth mode + real-Auth0 verify config. AUTH0 IS THE DEFAULT. jwt_issuer /
    # jwt_audience are None in STUB mode (unused), REQUIRED in AUTH0 mode (from_env
    # raises). auth0_jwks_url is derived from jwt_issuer when unset.
    #
    # THIS DEFAULT AND from_env's MUST AGREE. They are two separate sites for the same
    # decision, and a default changed in one and not the other is worse than changing
    # neither: the constructor and the environment path would disagree silently, and
    # every test that builds this dataclass directly would exercise the old behaviour.
    auth_mode: str = "AUTH0"
    jwt_issuer: str | None = None
    jwt_audience: str | None = None
    auth0_jwks_url: str | None = None
    # OPTIONAL Vertex AI config (see module docstring); never required. Both unset -> fallback.
    gemini_vertex_project: str | None = None
    gemini_vertex_location: str | None = None
    # OPTIONAL: SA to impersonate for Vertex calls only; unset -> ambient ADC.
    gemini_impersonate_sa: str | None = None
    # OPTIONAL operational knobs; None -> the suggester applies its own default.
    # Set-but-empty/unparseable does NOT reach here — from_env raises first (see helpers).
    gemini_model: str | None = None
    gemini_timeout_s: float | None = None
    gemini_thinking_budget: int | None = None
    # OPTIONAL Square OAuth; all unset -> the OAuth endpoints 503, rest of the BFF
    # unaffected. secrets project defaults to the pubsub project (same GCP project).
    square_client_id: str | None = None
    square_app_secret: str | None = None
    square_oauth_base_url: str = SQUARE_SANDBOX_OAUTH_BASE_URL
    square_oauth_redirect_uri: str | None = None
    square_secrets_project_id: str | None = None
    # CANONICAL, and deliberately NOT under the square_ prefix: the OAuth state-signing key
    # is a SHARED primitive every connector's connect flow uses (the mechanism in
    # oauth/state.py is vendor-agnostic and each vendor echoes `state` back verbatim).
    # Published unconditionally in the lifespan, so one vendor being unconfigured can never
    # take another vendor's connect flow down with it.
    oauth_state_key: str | None = None
    # OPTIONAL Clover OAuth (C3); all unset -> the Clover endpoints 503, everything else
    # unaffected. Separate from the Square block on purpose: one vendor's config must never
    # gate another's (see oauth_state_key above, which is why it is not in either block).
    clover_client_id: str | None = None
    clover_app_secret: str | None = None
    clover_oauth_base_url: str = CLOVER_SANDBOX_OAUTH_BASE_URL
    clover_oauth_redirect_uri: str | None = None
    clover_secrets_project_id: str | None = None

    @property
    def clover_oauth_configured(self) -> bool:
        """True only when every piece the Clover connect flow needs is present. base_url and
        the secrets project have defaults, so they never gate this; the state key is shared
        and checked by the handler, not here."""
        return all(
            (
                self.clover_client_id,
                self.clover_app_secret,
                self.clover_oauth_redirect_uri,
                self.oauth_state_key,
            )
        )

    @property
    def square_oauth_state_key(self) -> str | None:
        """Alias for :attr:`oauth_state_key`, kept ONLY so connectors_square.py and its
        tests need no edit. DERIVED, never separately parsed: two independent reads of one
        env var is how the two drift apart later. New connectors read the canonical field."""
        return self.oauth_state_key

    @property
    def square_oauth_configured(self) -> bool:
        """True only when every piece the connect flow needs is present (client id, app
        secret, redirect URI, state-signing key). base_url and secrets project have
        defaults, so they never gate this."""
        return all(
            (
                self.square_client_id,
                self.square_app_secret,
                self.square_oauth_redirect_uri,
                self.square_oauth_state_key,
            )
        )

    @property
    def square_oauth_environment(self) -> str:
        """sandbox vs production, derived from the OAuth host (stamped onto token sets)."""
        return "sandbox" if "squareupsandbox" in self.square_oauth_base_url else "production"

    @classmethod
    def from_env(cls) -> UiServerConfig:
        """Resolve from the environment, raising on any missing required value."""
        postgres_url = os.environ.get(_POSTGRES_URL)
        if not postgres_url:
            raise DisError(
                f"{_POSTGRES_URL} is not set; cannot reach the DIS database for the "
                "tenant-scoped readiness probe or any later data endpoint"
            )
        gcs_bucket_bronze = os.environ.get(_GCS_BUCKET_BRONZE)
        if not gcs_bucket_bronze:
            raise DisError(
                f"{_GCS_BUCKET_BRONZE} is not set; the CSV upload cannot build or "
                "write the canonical bronze object path"
            )
        pubsub_project_id = os.environ.get(_PUBSUB_PROJECT_ID)
        if not pubsub_project_id:
            raise DisError(
                f"{_PUBSUB_PROJECT_ID} is not set; the CSV upload cannot publish {CSV_RECEIVED_TOPIC!r}"
            )
        # =====================================================================================
        # AUTH MODE. THE DEFAULT IS AUTH0 AND IT USED TO BE STUB.
        # =====================================================================================
        # The old line was `os.environ.get(_DIS_AUTH_MODE) or "STUB"`, so an ABSENT env var
        # selected the HS256 dev-stub verifier with no error and no warning. That default is
        # fail-open: the stub accepts tokens signed with a symmetric secret, and the claims it
        # yields drive RLS, so a forged token would be a tenant-scoped read of somebody else's
        # data. Nothing was exploited, because the Terraform module defaults DIS_AUTH_MODE to
        # AUTH0 (cloud-run-service-dis-ui-server/variables.tf:80) and staging does not override
        # it. THAT IS THE PROBLEM RESTATED, NOT A MITIGATION: the application was safe only
        # while something outside it happened to be set correctly, and a deploy that dropped
        # the variable would have been silently insecure rather than broken.
        #
        # Inverting it makes the failure mode the safe one: an absent variable now selects the
        # RS256/JWKS verifier and then refuses to start without an issuer and an audience, so a
        # misconfiguration crashloops instead of accepting forged tokens.
        auth_mode = os.environ.get(_DIS_AUTH_MODE) or "AUTH0"
        if auth_mode not in ("STUB", "AUTH0"):
            raise DisError(f"{_DIS_AUTH_MODE}={auth_mode!r} is not a recognized mode; expected STUB or AUTH0")
        if auth_mode == "STUB":
            # ORDER IS DELIBERATE: the declaration is checked first, so a deployed process that
            # asked for STUB is refused for the reason that actually applies to it rather than
            # being told its database is the wrong shape.
            _refuse_stub_without_explicit_local_permission()
            _refuse_stub_against_a_remote_database(postgres_url)
        jwt_issuer = os.environ.get(_JWT_ISSUER) or None
        jwt_audience = os.environ.get(_JWT_AUDIENCE) or None
        auth0_jwks_url = os.environ.get(_AUTH0_JWKS_URL) or None
        if auth_mode == "AUTH0":
            if not jwt_issuer:
                raise DisError(f"{_JWT_ISSUER} is required when {_DIS_AUTH_MODE}=AUTH0")
            if not jwt_audience:
                raise DisError(f"{_JWT_AUDIENCE} is required when {_DIS_AUTH_MODE}=AUTH0")
            # Derive the JWKS endpoint from the issuer (Auth0 convention: the issuer
            # ends with '/'), mirroring Customer Master, unless explicitly overridden.
            if auth0_jwks_url is None:
                auth0_jwks_url = f"{jwt_issuer}.well-known/jwks.json"
        # OPTIONAL: read with no raise. Both unset -> the suggester uses the mechanical
        # fallback; missing Vertex config must never abort startup (FM1/FM2).
        gemini_vertex_project = os.environ.get(_GEMINI_VERTEX_PROJECT) or None
        gemini_vertex_location = os.environ.get(_GEMINI_VERTEX_LOCATION) or None
        gemini_impersonate_sa = os.environ.get(_GEMINI_IMPERSONATE_SA) or None
        # Gemini operational knobs: raise on set-but-empty/unparseable (fail loud), unset -> None.
        gemini_model = _optional_str_env(_GEMINI_MODEL)
        gemini_timeout_s = _optional_float_env(_GEMINI_TIMEOUT_S)
        gemini_thinking_budget = _optional_int_env(_GEMINI_THINKING_BUDGET)
        # OPTIONAL Square OAuth: read with no raise; unset -> the endpoints 503.
        square_client_id = os.environ.get(_SQUARE_CLIENT_ID) or None
        square_app_secret = os.environ.get(_SQUARE_APP_SECRET) or None
        square_oauth_base_url = os.environ.get(_SQUARE_OAUTH_BASE_URL) or SQUARE_SANDBOX_OAUTH_BASE_URL
        square_oauth_redirect_uri = os.environ.get(_SQUARE_OAUTH_REDIRECT_URI) or None
        oauth_state_key = os.environ.get(_OAUTH_STATE_KEY) or None
        clover_client_id = os.environ.get(_CLOVER_CLIENT_ID) or None
        clover_app_secret = os.environ.get(_CLOVER_APP_SECRET) or None
        clover_oauth_base_url = os.environ.get(_CLOVER_OAUTH_BASE_URL) or CLOVER_SANDBOX_OAUTH_BASE_URL
        clover_oauth_redirect_uri = os.environ.get(_CLOVER_OAUTH_REDIRECT_URI) or None
        clover_secrets_project_id = os.environ.get(_CLOVER_SECRETS_PROJECT_ID) or pubsub_project_id
        square_secrets_project_id = os.environ.get(_SQUARE_SECRETS_PROJECT_ID) or pubsub_project_id
        return cls(
            postgres_url=postgres_url,
            gcs_bucket_bronze=gcs_bucket_bronze,
            pubsub_project_id=pubsub_project_id,
            auth_mode=auth_mode,
            jwt_issuer=jwt_issuer,
            jwt_audience=jwt_audience,
            auth0_jwks_url=auth0_jwks_url,
            gemini_vertex_project=gemini_vertex_project,
            gemini_vertex_location=gemini_vertex_location,
            gemini_impersonate_sa=gemini_impersonate_sa,
            gemini_model=gemini_model,
            gemini_timeout_s=gemini_timeout_s,
            gemini_thinking_budget=gemini_thinking_budget,
            square_client_id=square_client_id,
            square_app_secret=square_app_secret,
            square_oauth_base_url=square_oauth_base_url,
            square_oauth_redirect_uri=square_oauth_redirect_uri,
            oauth_state_key=oauth_state_key,
            clover_client_id=clover_client_id,
            clover_app_secret=clover_app_secret,
            clover_oauth_base_url=clover_oauth_base_url,
            clover_oauth_redirect_uri=clover_oauth_redirect_uri,
            clover_secrets_project_id=clover_secrets_project_id,
            square_secrets_project_id=square_secrets_project_id,
        )


def cors_allowed_origins_from_env() -> tuple[str, ...]:
    """The CORS origin allow-list, comma-separated from ``CORS_ALLOWED_ORIGINS``.

    Resolved at APP-BUILD time in ``create_app`` — not in the lifespan like
    ``UiServerConfig.from_env`` — because Starlette middleware must be
    registered before startup, while the lifespan-resolves-config posture is
    test-pinned for the crashloop-on-missing-POSTGRES_URL split. Same mechanism
    (env read in this module), different resolution point; safe at import
    because the value has a sanctioned default (the slice contract mandates the
    confirmed dis-ui dev origin) and so can never abort an import.

    Unset → the dev default. Set-but-empty is an ambiguous declaration and
    raises (code-quality rule 4): unset it for the default, or list explicit
    origins.
    """
    raw = os.environ.get(_CORS_ALLOWED_ORIGINS)
    if raw is None:
        return _DEFAULT_CORS_ORIGINS
    origins = tuple(origin.strip() for origin in raw.split(",") if origin.strip())
    if not origins:
        raise DisError(
            f"{_CORS_ALLOWED_ORIGINS} is set but contains no origins; unset it for "
            "the dev default or list explicit comma-separated origins"
        )
    return origins
