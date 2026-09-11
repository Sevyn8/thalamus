# syntax=docker/dockerfile:1.7

# ---------- Stage 1: builder ----------
FROM python:3.12-slim AS builder

# uv installs deps fast and respects uv.lock for reproducibility.
COPY --from=ghcr.io/astral-sh/uv:0.5.4 /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

WORKDIR /build

# Copy only dep manifests first to maximise layer cache.
COPY pyproject.toml uv.lock ./

# Install runtime deps only (no dev group).
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Copy source and install the project itself (puts the package in /opt/venv).
COPY src/ ./src/
COPY README.md ./README.md
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# ---------- Stage 2: runtime ----------
FROM python:3.12-slim AS runtime

# Non-root user. Cloud SQL Auth Proxy sidecar (prod only) runs as its own UID;
# this is just for the app.
RUN groupadd --system --gid 1000 app \
 && useradd --system --uid 1000 --gid app --create-home --shell /usr/sbin/nologin app

# SERVICE_VERSION is baked into the image at build time so /api/v1/health
# reports the image tag without any deploy-time env-var setup. Pass via
# `docker build --build-arg SERVICE_VERSION=v0.1.4 ...`. Default `dev`
# only fires when the build script forgets to pass it (and is loud enough
# in /api/v1/health to be noticed). Cloud Run / GKE can still override
# at deploy time by setting the SERVICE_VERSION env var, which takes
# precedence over the baked default.
ARG SERVICE_VERSION=dev

ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH="/app/src" \
    SERVICE_VERSION=${SERVICE_VERSION}

# THE ASGI TARGET, DECLARED ONCE. The build-check below and the CMD at the bottom
# both read this variable, so the string uvicorn resolves at startup is literally
# the string the build verified.
#
# WRITING IT TWICE SHIPPED A DEAD IMAGE ON THE OTHER SERVICE IN THIS ESTATE.
# synapse-ui-server's CMD said `main:app` while its check imported `create_app`:
# the check passed, because create_app existed and built, and the container then
# died on `Attribute "app" not found in module`. One copy was checked and the
# other shipped. That is the duplication class this file is now protected from.
#
# `:app` AND NOT `:create_app`, WHICH IS THE OPPOSITE CHOICE FROM synapse-ui-server
# AND IS NOT A STYLE DIFFERENCE. main.py ends with `app = create_app()` at module
# level, so importing the module BUILDS the app, which means importing it requires
# the runtime environment. The check below supplies it. A factory target would be
# the better shape and changing it is an application change, which this slice is
# not; the check is written against what the service actually does.
ENV ASGI_TARGET="admin_backend.main:app"

WORKDIR /app

# Bring the venv from the builder.
COPY --from=builder --chown=app:app /opt/venv /opt/venv

# Application source. Migrations are bundled because the image is also used
# as the alembic-runner for schema bring-up.
COPY --chown=app:app src/ /app/src/
COPY --chown=app:app migrations/ /app/migrations/
COPY --chown=app:app alembic.ini /app/alembic.ini

# Cloud Run Job verification scripts. Selective copy: only the
# scripts intended to run inside the image. Dev-only tooling (check_setup.sh,
# excel_to_seed_sql.py, apply_seeds.sh) stays excluded via .dockerignore.
COPY --chown=app:app scripts/verify_cloud_schema.py /app/scripts/verify_cloud_schema.py
COPY --chown=app:app scripts/smoke_test.py /app/scripts/smoke_test.py

# ============================================================================
# BUILD-TIME CHECK: RESOLVE $ASGI_TARGET EXACTLY AS UVICORN WILL, THEN ASSERT
# THAT THE ROUTERS REGISTERED.
# ============================================================================
# IT RUNS IN THE RUNTIME STAGE, AFTER EVERY COPY, ON PURPOSE. The builder stage
# has the venv and the source too, so the check would pass there; but it would be
# checking a layout that is not the one that ships. Here it exercises the real
# PATH, the real PYTHONPATH=/app/src and the real /app/src tree, so a COPY that
# lands in the wrong place fails the build rather than the first request.
#
# `uvicorn.importer.import_from_string` IS UVICORN'S OWN RESOLVER, not a
# reimplementation. Using the real function against the real string means the only
# way this passes while startup fails is a uvicorn bug.
#
# THE FOUR VARIABLES ARE THE FOUR Settings HAS NO DEFAULT FOR. Importing the module
# runs `app = create_app()`, which calls get_settings(), so the import genuinely
# needs them. They are build-time only, are never persisted into the image, and are
# syntactically valid rather than reachable; Cloud Run supplies the real ones.
#
# NOTE THAT THE IMAGE HAS NO .env AND THAT IS LOAD-BEARING HERE. Settings declares
# `env_file=PROJECT_ROOT / ".env"`, and .dockerignore excludes it, so inside the
# image these four are the only source. On a developer machine cm-backend/.env
# exists and would fill in the gaps silently, which is why the test that guards
# this list disables the env file rather than trusting the environment.
#
# tests/test_dockerfile_build_check.py PARSES THIS BLOCK and compares both sets
# against the running article, in BOTH DIRECTIONS: a name here the service does not
# require fails just as loudly as one it requires and this list lacks. An unparsed
# check goes stale and keeps passing while asserting less than it claims, which is
# exactly what happened to the equivalent list on synapse-ui-server, twice.
#
# THE ROUTE SET IS ONE REPRESENTATIVE PER ROUTER, NOT EVERY ROUTE, AND THE TEST
# ENFORCES THAT RULE RATHER THAN THE LIST. This service registers 73 (path, method)
# pairs across 19 routers, 29 of them under /api/v1/tenants alone, and the realistic
# failure is a whole router failing to include rather than one path vanishing from a
# router that otherwise works. A hand-sampled subset is what went wrong on
# synapse-ui-server, so the subset here is mechanical: the test fails when a router
# appears with no representative, so a new router cannot land unasserted.
RUN DATABASE_URL="postgresql+psycopg://build@build.invalid/build" \
    DB_SCHEMA="core" \
    JWT_ISSUER="https://build.invalid/" \
    JWT_AUDIENCE="build-check" \
    python -c "\
import os; \
from uvicorn.importer import import_from_string; \
target = os.environ['ASGI_TARGET']; \
app = import_from_string(target); \
routes = {(r.path, m) for r in app.routes if hasattr(r, 'path') for m in (getattr(r, 'methods', None) or {'GET'})}; \
required = { \
    ('/api/v1/health', 'GET'), \
    ('/api/v1/ready', 'GET'), \
    ('/api/v1/me/permissions', 'GET'), \
    ('/api/v1/audit/activities', 'GET'), \
    ('/api/v1/channels', 'GET'), \
    ('/api/v1/dashboard/fleet-stats', 'GET'), \
    ('/api/v1/lookups', 'GET'), \
    ('/api/v1/module-access/me', 'GET'), \
    ('/api/v1/permission-matrix', 'GET'), \
    ('/api/v1/permissions', 'GET'), \
    ('/api/v1/platform-users', 'GET'), \
    ('/api/v1/role-assignments', 'GET'), \
    ('/api/v1/roles', 'GET'), \
    ('/api/v1/stores', 'GET'), \
    ('/api/v1/tenant-users', 'GET'), \
    ('/api/v1/tenants', 'GET'), \
    ('/api/v1/docs', 'GET'), \
    ('/api/v1/redoc', 'GET'), \
    ('/api/v1/openapi.json', 'GET'), \
    ('/docs/oauth2-redirect', 'GET'), \
}; \
missing = required - routes; \
assert not missing, f'routes did not register: {sorted(missing)}'; \
print(f'{target} resolves and registers {len(routes)} routes, {len(required)} asserted')"

USER app

# Documentation only; Cloud Run routes to the port it injects via $PORT.
EXPOSE 8080

# Default command: run the FastAPI app. Honors Cloud Run's injected $PORT
# (defaults to 8080 for local runs). sh -c expands $PORT; `exec` replaces the
# shell with uvicorn so SIGTERM reaches the app for graceful shutdown.
# Cloud Run / GKE Job overrides CMD with `alembic upgrade head` for schema
# bring-up; the app itself never runs migrations on boot.
#
# READS $ASGI_TARGET rather than repeating the string. The build-check above
# resolved that exact variable, so the two cannot disagree. See the ENV for what
# it cost the other service to write it twice.
CMD ["/bin/sh", "-c", \
     "exec uvicorn \"$ASGI_TARGET\" --host 0.0.0.0 --port ${PORT:-8080} --no-server-header"]
