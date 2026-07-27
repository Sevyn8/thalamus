# thalamus-clover — the Clover connector, run as a Cloud Run JOB.
#
# One execution is ONE trigger: python -m thalamus_clover.real_transport mints the
# producer-owned ids, builds a ConnectorTrigger, and runs a single Clover catalog pull
# (extract -> CSV -> bronze -> ingress.ready). There is no loop and no server, so this
# image exposes no port and has no health path.
#
# The run target is NOT baked in: the container carries no default args, and every
# execution supplies them via `gcloud run jobs execute --args`. A bare execute fails on
# argparse with exit 2, deliberately (a multi-tenant connector must not have a default
# tenant). Deployed by infra/modules/cloud-run-service-clover-connector.
#
# The build context is the MONOREPO ROOT: the uv workspace is rooted at dis/ and declares
# members at ../connectors/* (siblings of dis/), so a dis/-rooted context can never provide
# them. Every COPY is therefore prefixed, and the connectors land at /connectors so uv's
# ../connectors/* sources resolve (../connectors from /app == /connectors).
#
# THE COPY SET IS DERIVED FROM THIS PACKAGE'S CLOSURE, NOT COPIED FROM THE SQUARE IMAGE.
# thalamus-clover resolves to nine workspace members: itself, thalamus-connector-sdk and
# thalamus-clover-oauth; dis-core, dis-rls, dis-storage, dis-audit and dis-pii; and
# csv-ingest-worker (the SDK reuses its bronze sink, publisher seam and ingress.ready topic
# name). Two consequences worth stating, because both differ from the Square image:
#
#   - NO dis-canonical. Square declares it for a header drift-guard; Clover does not.
#   - ONLY csv-ingest-worker among the dis services. The Square image copies all four "for
#     parity", which ships dis-ui-server's entire source inside a connector. Copying a BFF
#     into a connector image earns nothing, so this image copies what it needs. Verified:
#     `uv sync --frozen --no-dev --package thalamus-clover` succeeds against exactly this
#     set (54 packages), and an absent NON-closure member is not an error - only a member
#     inside the closure must be present.
#
# Canonical build command (run from the monorepo root):
#
#   docker build -f connectors/thalamus-clover/Dockerfile -t clover-connector .

FROM python:3.12-slim

# uv pinned to the minor the repo develops against (uv 0.11 locally).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Connectors workspace members, at /connectors so the workspace's ../connectors/* sources
# resolve. All three are in this image's closure: thalamus-clover itself, the SDK it
# implements, and the SDK-free OAuth/Secret Manager token vault CloverTokenStore reads.
COPY connectors/sdk /connectors/sdk
COPY connectors/thalamus-clover /connectors/thalamus-clover
COPY connectors/clover-oauth /connectors/clover-oauth

# The dis workspace skeleton: root project + the members this closure actually reaches.
COPY dis/pyproject.toml dis/uv.lock ./
COPY dis/libs libs
COPY dis/services/csv-ingest-worker services/csv-ingest-worker

# Install ONLY this connector's dependency closure, locked (--frozen: the lock is
# authoritative; a drifted lock fails the build instead of resolving silently).
RUN uv sync --frozen --no-dev --package thalamus-clover

ENV PATH="/app/.venv/bin:$PATH"

# IMPORT THE ENTRYPOINT AT BUILD TIME. real_transport pulls in the pipeline, the adapter,
# the puller and the token store, so this executes the whole import graph and turns an
# undeclared dependency, a missing COPY or a circular import into a BUILD failure instead
# of a green image whose every execution dies on startup.
#
# No local gate catches that class: the uv workspace dev group installs every member, so
# mypy and the full test suite pass against modules that are not in the image. dis-ui-server
# shipped exactly that defect today - green build, clean push, ModuleNotFoundError in the
# container. This line is the only place the image's ACTUAL closure is exercised.
RUN python -c "import thalamus_clover.real_transport"

# Non-root (the connector writes no local filesystem at runtime; the CSV it produces is
# serialized in memory and streamed to the bronze bucket).
RUN useradd --system --no-create-home cloverconnector
USER cloverconnector

# ENTRYPOINT, not CMD. Cloud Run's `--args` replaces the container's ARGS (docker CMD) and
# leaves the COMMAND (docker ENTRYPOINT) intact, so putting the module invocation in
# ENTRYPOINT means an execution passes only the run target:
# `--args="--tenant-id,...,--run-key,..."`. With CMD the caller would have to re-supply
# `python,-m,thalamus_clover.real_transport` every time. No EXPOSE: a Job serves nothing.
ENTRYPOINT ["python", "-m", "thalamus_clover.real_transport"]
