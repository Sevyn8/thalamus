# migrate-dis — the way DIS's alembic chain reaches a database
#
# A RUN-TO-COMPLETION job carrying nothing but the chain: `alembic upgrade head`, exit.
# It runs no DIS service code and imports none — verified, not assumed: every module under
# alembic/versions/ imports only `alembic`, `sqlalchemy`, `pathlib`, `os`, `datetime` and
# `typing`, and env.py the same. So no lib and no service directory is copied below.
#
# WHY THE ROOT PROJECT IS THE CARRIER, and why this image exists at all rather than the
# migration riding an existing service image the way migrate-cm rides cm-backend's.
#
# For Synapse the chain lives INSIDE the synapse package, so the orchestrator image already
# carried it and reusing that image was free. DIS's chain does not live in a service:
# alembic.ini, alembic/ and schemas/ sit at the WORKSPACE ROOT, owned by the root
# `ithina-dis` project — which is also the only DIS project that declares alembic
# (pyproject.toml:16). Measured: `uv tree --frozen --no-dev --package <svc>` returns ZERO
# alembic occurrences for csv-ingest-worker, streaming-consumer, mirror-sync-consumer and
# dis-ui-server. Every service image syncs its own package, so a root dependency never
# reaches them.
#
# So every existing image would need BOTH a new dependency AND three COPY lines, and adding
# alembic to one service's pyproject rewrites the shared uv.lock — which invalidates the
# `uv sync` layer for ALL FOUR sibling images on their next build (same package set,
# different build). Carrying the chain in the package that owns it costs zero dependency
# change and zero sibling churn.
#
# WHAT IS NOT AVAILABLE HERE, stated rather than implied: migrate-cm's D6 property that the
# migration runs the SAME BUILD as the workload it migrates for. DIS has four workloads on
# one schema, so pinning the migration to any single service image would give that property
# for that one service and silently not for the other three. A dedicated image makes the
# absence explicit.
#
# THIS IMAGE IS FAT AND THAT IS A DELIBERATE TRADE. The root closure is 139 wheels including
# dbt-bigquery, duckdb, polars and pyarrow, none of which any migration imports. Narrowing it
# would mean a new extra or dependency-group in dis/pyproject.toml, and the only group that
# exists is `dev`. That edit would churn uv.lock and reintroduce exactly the sibling-rebuild
# effect this image was chosen to avoid, to save pull time on a job that runs on deploys.
# Not worth it. Re-evaluate only if a narrower group appears for another reason.
#
# THE COPY SET IS THE MIGRATION'S RUNTIME NEED, derived rather than guessed:
#
#   alembic.ini   `script_location = %(here)s/alembic` — resolved against the ini's own
#                 directory, so the ini and the chain must stay siblings.
#   alembic/      the 19 revisions plus env.py.
#   schemas/      FIVE revisions read DDL off disk — 0001, 0007, 0009, 0013, 0016 — each
#                 resolving `Path(__file__).resolve().parents[2] / "schemas" / "postgres"`.
#                 From /app/alembic/versions/X.py that is /app/schemas/postgres, which is
#                 why schemas/ lands at the WORKDIR and not anywhere else. 0001's manifest
#                 alone is 16 .sql files; a missing one is a mid-chain failure, not a
#                 startup one.
#
# Build from the dis/ WORKSPACE ROOT (not the repo root, not terraform/docker):
#
#   docker build -f terraform/docker/migrate-dis.Dockerfile -t migrate-dis .
#
# No `# syntax=` directive and no heredocs, so the classic builder is sufficient; unlike the
# dis-ui-ver2 image this needs no DOCKER_BUILDKIT=1.

FROM python:3.12-slim

# uv pinned to the minor the repo develops against, matching every other image here.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# The root project only. No workspace member is copied: `[tool.uv] package = false` makes
# the root a virtual project, so this installs its DEPENDENCIES and builds no first-party
# package — which is all the chain needs.
COPY pyproject.toml uv.lock ./

# --frozen: the lock is authoritative; a drifted lock fails the build instead of resolving
# to something else. --no-dev: the `dev` group is the only group and holds none of this.
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

# The chain itself, after the sync so a revision edit does not invalidate the dependency
# layer. schemas/ is a runtime input to five revisions, not documentation — see the header.
COPY alembic.ini ./alembic.ini
COPY alembic ./alembic
COPY schemas ./schemas

# BUILD-TIME CHECK, and here it is the one that matters most. `alembic heads` builds the
# revision map, which IMPORTS every module under alembic/versions/ — so a syntax error, a
# missing dependency or a dangling down_revision fails the BUILD rather than the first run
# against a real database.
#
# `heads` SPECIFICALLY, not `history` or `current`: it is the only one of the three that does
# not call run_env(), so it never imports env.py — which resolves POSTGRES_ADMIN_URL at module
# scope and RAISES when it is unset (env.py:80, :58). There is no DSN at build time and no
# .env in this image, so a command that loaded env.py would fail every build. Verified both
# ways: alembic/command.py's heads() has no run_env, and the command runs clean in a tree with
# no .env and the variable unset.
#
# EXACT STRING COMPARISON, not a grep. `heads` prints ONE LINE PER HEAD, so a forked chain
# prints two — and `grep -q 0019` matches happily on the fork, which is the failure this check
# most needs to catch. Proven by breaking it both ways before shipping: a syntax error exits
# non-zero, and repointing 0019's down_revision to 0017 prints "0018 (head)\n0019 (head)",
# which passes a grep and fails this.
#
# Update the expected head in the SAME commit that adds a revision.
RUN test "$(alembic -c /app/alembic.ini heads)" = "0019 (head)"

# Non-root. The migration writes Postgres, never the local filesystem.
RUN useradd --system --no-create-home dismigrate
USER dismigrate

# No EXPOSE: a run-to-completion job serves no port.
#
# ENTRYPOINT is the safe default rather than the mechanism the job relies on — the Cloud Run
# module sets command AND args explicitly, matching migrate-cm and migrate-synapse. Both of
# those override a CMD that would otherwise start a SERVER (uvicorn, and Synapse's sweep),
# where the failure mode is a hung job rather than a visible wrong command. Nothing here
# starts a server, so this line is a convenience for `docker run`; the module does not
# depend on it and must keep its override.
ENTRYPOINT ["alembic", "-c", "/app/alembic.ini", "upgrade", "head"]
