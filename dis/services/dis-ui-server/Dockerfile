# dis-ui-server — the DIS UI backend-for-frontend.
#
# The build context is the MONOREPO ROOT. The uv workspace is rooted at dis/ and
# declares members at ../connectors/* (siblings of dis/), so a dis/-rooted context
# can never provide them. Every COPY is therefore dis/-prefixed, and the connectors
# workspace members in this service's dependency closure are copied to /connectors
# (beside the /app workspace root) so uv's ../connectors/* sources resolve.
#
# Canonical build command (run from the monorepo root):
#
#   docker build -f dis/services/dis-ui-server/Dockerfile -t dis-ui-server .
#
# Run (the container needs POSTGRES_URL; /healthz answers without a DB):
#
#   docker run --rm -p 8080:8080 \
#     -e POSTGRES_URL=postgresql+psycopg://ithina_dis_user:...@host:5433/ithina_dis_db \
#     dis-ui-server

FROM python:3.12-slim

# uv pinned to the minor the repo develops against (uv 0.11 locally).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Connectors workspace members in dis-ui-server's closure, at /connectors so the
# workspace's ../connectors/* sources resolve (../connectors from /app == /connectors).
# dis-ui-server depends on thalamus-square-oauth and thalamus-clover-oauth; both are
# SDK-free (deps: dis-core, google-cloud-secret-manager, httpx), so connectors/sdk,
# connectors/thalamus-square and connectors/thalamus-clover are NOT in the closure and are
# not copied.
COPY connectors/square-oauth /connectors/square-oauth
COPY connectors/clover-oauth /connectors/clover-oauth

# The dis workspace skeleton: root project + the declared members this build reaches.
# Explicit COPYs keep the image free of repo junk regardless of context contents.
COPY dis/pyproject.toml dis/uv.lock ./
COPY dis/libs libs
COPY dis/services/mirror-sync-consumer services/mirror-sync-consumer
COPY dis/services/csv-ingest-worker services/csv-ingest-worker
COPY dis/services/streaming-consumer services/streaming-consumer
COPY dis/services/dis-ui-server services/dis-ui-server

# Install ONLY this service's dependency closure, locked (--frozen: the lock is
# authoritative; a drifted lock fails the build instead of resolving silently).
RUN uv sync --frozen --no-dev --package dis-ui-server

ENV PATH="/app/.venv/bin:$PATH"

# IMPORT THE APP AT BUILD TIME. api.py imports every handler, so this executes the whole
# import graph and turns an undeclared dependency, a missing COPY or a circular import into
# a BUILD failure instead of a green image whose every container dies on startup.
#
# No local gate can catch that class: the uv workspace dev group installs every member, so
# mypy and the full test suite pass against modules that are not in the image. This line is
# the only place the image's ACTUAL closure is exercised.
RUN python -c "import dis_ui_server.api"

# Non-root (the service needs no filesystem writes at runtime).
RUN useradd --system --no-create-home disui
USER disui

EXPOSE 8080

CMD ["uvicorn", "dis_ui_server.main:app", "--host", "0.0.0.0", "--port", "8080"]
