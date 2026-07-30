# mirror-sync-consumer
#
# A RUN-TO-COMPLETION job, not a service, despite the name. One invocation = one
# sync pass = exit. It reads Customer Master's core.tenants / core.stores under a
# PLATFORM read context and upserts identity_mirror.tenants / .stores, then exits
# with a meaningful code (0 ok, 2 config, 3 CM target/context, 4 CM unreachable,
# 5 DIS write-guard, 6 write). Entrypoint:
# services/mirror-sync-consumer/src/mirror_sync_consumer/pull/runner.py, whose
# `if __name__ == "__main__": raise SystemExit(main())` is what propagates the exit
# code to Cloud Run. Deployed as a Cloud Run JOB (see
# infra/modules/cloud-run-job-mirror-sync-consumer).
#
# Mirrors services/csv-ingest-worker's Dockerfile: the service is a uv-workspace
# member, so the build context is the dis/ workspace root and the workspace member
# directories are copied explicitly. Build with:
#
#   docker build -f terraform/docker/mirror-sync-consumer.Dockerfile \
#     -t mirror-sync-consumer .
#
# THE COPY SET IS THE RESOLVED CLOSURE, NOT A SUPERSET. Derived, not guessed:
#
#   uv tree --frozen --no-dev --package mirror-sync-consumer
#     -> first-party members: dis-core, dis-rls, mirror-sync-consumer
#
# so only those two libs are copied rather than all twelve. uv refuses a missing
# workspace member ONLY when it is inside the target package's closure; a declared
# member outside it may be absent and `uv sync --frozen --package <name>` still
# succeeds (the connectors have shipped on exactly that basis since C2). Re-derive
# with the command above rather than trusting this list. If a future dependency
# lands outside the two libs here, the build fails loudly at `uv sync` - which is
# the point of pinning the closure instead of copying everything.
#
# No `# syntax=` directive and no heredocs, so the classic builder is sufficient;
# unlike the dis-ui-ver2 image this needs no DOCKER_BUILDKIT=1.

FROM python:3.12-slim

# uv pinned to the minor the repo develops against (uv 0.11 locally).
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The workspace skeleton: root project plus exactly this package's closure.
COPY pyproject.toml uv.lock ./
COPY libs/dis-core libs/dis-core
COPY libs/dis-rls libs/dis-rls
COPY services/mirror-sync-consumer services/mirror-sync-consumer

# Install ONLY this service's dependency closure, locked (--frozen: the lock is
# authoritative; a drifted lock fails the build instead of resolving silently).
RUN uv sync --frozen --no-dev --package mirror-sync-consumer

ENV PATH="/app/.venv/bin:$PATH"

# Build-time import check (batch-1 pattern, added to the connectors): a broken
# entrypoint or a missing transitive dep fails the BUILD rather than the first
# execution. Safe to run here - runner.py does all its work inside main() under
# `if __name__ == "__main__"`, so importing it connects to nothing.
RUN python -c "import mirror_sync_consumer.pull.runner"

# Non-root (the job writes no local filesystem).
RUN useradd --system --no-create-home disworker
USER disworker

# No EXPOSE: a run-to-completion job serves no port. There is no health server
# here, unlike the csv-ingest-worker image this is adapted from.

CMD ["python", "-m", "mirror_sync_consumer.pull.runner"]
