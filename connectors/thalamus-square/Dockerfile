# thalamus-square — the Square connector, run as a Cloud Run JOB.
#
# One execution is ONE trigger: python -m thalamus_square.real_transport mints the
# producer-owned ids, builds a ConnectorTrigger, and runs a single Square catalog pull
# (extract -> CSV -> bronze -> ingress.ready). There is no loop and no server, so this
# image exposes no port and has no health path — unlike the two DIS worker images.
#
# The run target is NOT baked in: the container carries no default args, and every
# execution supplies them via `gcloud run jobs execute --args`. A bare execute fails on
# argparse with exit 2, deliberately (a multi-tenant connector must not have a default
# tenant). Deployed by infra/modules/cloud-run-service-square-connector.
#
# The build context is the MONOREPO ROOT, following the proven
# dis/services/dis-ui-server/Dockerfile rather than the dis/-rooted
# dis/terraform/docker/*.Dockerfile pair. Reason: the uv workspace is rooted at dis/ and
# declares members at ../connectors/* (siblings of dis/), so a dis/-rooted context can
# never provide them. The two DIS worker images get away with a dis/-rooted context only
# because no connectors member is in their dependency closure.
#
# THE COPY SET IS DERIVED FROM THIS PACKAGE'S CLOSURE. Run
# `uv tree --frozen --no-dev --package thalamus-square` from dis/: it resolves to TEN
# workspace members — thalamus-square itself, thalamus-connector-sdk and
# thalamus-square-oauth; dis-core, dis-canonical, dis-rls, dis-storage, dis-audit and
# dis-pii; and csv-ingest-worker (the SDK reuses its bronze sink, publisher seam and
# ingress.ready topic name). That is ALL THREE connectors members and exactly ONE dis
# service.
#
# The other three dis services used to be copied here "for parity" with the dis-ui-server
# image, which shipped dis-ui-server's entire source inside a connector image. They are
# not reachable from thalamus-square at all and are gone. The set differs from the Clover
# image's by exactly dis-canonical (Square declares it for a header drift-guard; Clover
# does not), which is the check that this was derived rather than copied.
#
# Every COPY is therefore prefixed, and the connectors land at /connectors so uv's
# ../connectors/* sources resolve (../connectors from /app == /connectors).
#
# Canonical build command (run from the monorepo root):
#
#   docker build -f connectors/thalamus-square/Dockerfile -t square-connector .

FROM python:3.12-slim

# uv pinned to the minor the repo develops against (uv 0.11 locally).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Connectors workspace members, at /connectors so the workspace's ../connectors/* sources
# resolve. All three are in this image's closure: thalamus-square itself, the SDK it
# implements, and the SDK-free OAuth/Secret Manager token vault the VaultTokenStore reads.
COPY connectors/sdk /connectors/sdk
COPY connectors/thalamus-square /connectors/thalamus-square
COPY connectors/square-oauth /connectors/square-oauth

# The dis workspace skeleton: root project + the members this closure actually reaches.
# uv does NOT require every declared workspace member to be present — only the members
# inside the TARGET PACKAGE'S CLOSURE — so mirror-sync-consumer, streaming-consumer and
# dis-ui-server are absent and the build still resolves. Removing a member that IS in the
# closure (csv-ingest-worker, or any of dis/libs) fails the build, which is the proof.
COPY dis/pyproject.toml dis/uv.lock ./
COPY dis/libs libs
COPY dis/services/csv-ingest-worker services/csv-ingest-worker

# Install ONLY this connector's dependency closure, locked (--frozen: the lock is
# authoritative; a drifted lock fails the build instead of resolving silently).
RUN uv sync --frozen --no-dev --package thalamus-square

ENV PATH="/app/.venv/bin:$PATH"

# IMPORT THE ENTRYPOINT AT BUILD TIME. real_transport pulls in the pipeline, the adapter,
# the puller and the token store, so this executes the whole import graph and turns an
# undeclared dependency, a missing COPY or a circular import into a BUILD failure instead
# of a green image whose every execution dies on startup.
#
# No local gate catches that class: the uv workspace dev group installs every member, so
# mypy and the full test suite pass against modules that are not in the image. dis-ui-server
# shipped exactly that defect once - green build, clean push, ModuleNotFoundError in the
# container. This line is the only place the image's ACTUAL closure is exercised, and it is
# also what proves the root .dockerignore's dev_transport/fakes exclusion is safe.
RUN python -c "import thalamus_square.real_transport"

# Non-root (the connector writes no local filesystem at runtime; the CSV it produces is
# serialized in memory and streamed to the bronze bucket).
RUN useradd --system --no-create-home squareconnector
USER squareconnector

# ENTRYPOINT, not CMD (the divergence from the three DIS images, which take no args and
# use CMD). Cloud Run's `--args` replaces the container's ARGS (docker CMD) and leaves the
# COMMAND (docker ENTRYPOINT) intact, so putting the module invocation in ENTRYPOINT means
# an execution passes only the run target: `--args="--tenant-id,...,--run-key,..."`. With
# CMD the caller would have to re-supply `python,-m,thalamus_square.real_transport` on
# every execute. No EXPOSE: a Job serves nothing. No default args: see the header.
ENTRYPOINT ["python", "-m", "thalamus_square.real_transport"]
