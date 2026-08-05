# thalamus-synapse — the Synapse orchestrator, run as a Cloud Run JOB.
#
# One execution is ONE SWEEP: `python -m synapse.orchestrator` enumerates every active
# provision, works out each tenant's due slot in that tenant's own timezone, resolves and
# evaluates the declaration, appends actions, and records a run. There is no loop and no
# server, so this image exposes no port and has no health path.
#
# SHADOW ONLY. The sweep computes, records to synapse.actions and synapse.run, and delivers
# nothing to anyone. Any rung above SHADOW is refused by the orchestrator rather than
# approximated.
#
# NO DEFAULT ARGS, which is what keeps the hand-run and the scheduled run the same thing. The
# scheduled execution supplies none and gets the full sweep; an operator supplies `--dry-run`,
# `--tenant` or `--now` via `gcloud run jobs execute --args`. The connectors set this precedent
# deliberately, and it is why scheduling is an ADDITION rather than a replacement: there is one
# code path with two callers, so the two cannot drift.
#
# THE BUILD CONTEXT IS THE MONOREPO ROOT, and this is structural rather than a preference. The
# uv workspace is rooted at dis/ and declares this package as "../synapse" — a sibling of dis/,
# exactly like connectors/*. A dis/-rooted context therefore cannot reach it at all. Every COPY
# below is prefixed accordingly, and synapse lands at /synapse so the workspace's ../synapse
# source resolves (../synapse from /app == /synapse). This is the connectors' strategy, NOT
# mirror-sync-consumer's, whose context is dis/ because it is a member of dis/.
#
# THE COPY SET IS RESOLVED, NOT GUESSED. `uv tree --package thalamus-synapse` gives exactly
# three workspace members beyond synapse itself:
#
#   dis-canonical  -> canonical ROW SHAPES; every row Synapse reads is validated through these
#   dis-rls        -> the two-GUC session discipline + the wrong-database / bypassing-role guard
#   dis-core       -> UUIDv7 (ids.new_uuid7) and the JSON logger that emits `severity`
#
# and nothing else: no services, no connectors, no dis-testing, none of dis-pii / dis-storage /
# dis-audit. That set was assembled in a scratch tree and `uv sync --frozen --no-dev --package
# thalamus-synapse` run against it — 21 packages, resolves clean — so the absence of every other
# workspace member is verified for THIS package rather than inherited from the Clover image's
# note. Only a member inside the closure must be present.
#
# Canonical build command (run from the monorepo root):
#
#   docker build -f synapse/Dockerfile -t synapse-orchestrator .

FROM python:3.12-slim

# uv pinned to the minor the repo develops against, matching every other image here.
COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Synapse itself, at /synapse so the workspace's ../synapse member source resolves.
COPY synapse /synapse

# The dis workspace skeleton: the root project plus the three libs this closure reaches.
COPY dis/pyproject.toml dis/uv.lock ./
COPY dis/libs/dis-core /app/libs/dis-core
COPY dis/libs/dis-canonical /app/libs/dis-canonical
COPY dis/libs/dis-rls /app/libs/dis-rls

# Install ONLY this package's dependency closure, locked. --frozen makes the lock
# authoritative: a drifted lock fails the build instead of resolving to something else.
RUN uv sync --frozen --no-dev --package thalamus-synapse

ENV PATH="/app/.venv/bin:$PATH"

# IMPORT THE ENTRYPOINT AT BUILD TIME, and here it buys more than it does elsewhere.
#
# For the connectors this catches an undeclared dependency, a missing COPY or a circular import
# — a green image whose every execution dies on startup, which dis-ui-server actually shipped.
# It catches all of that here too.
#
# It also does something specific to Synapse: importing this module executes the REGISTRY's
# import-time invariants — _check_registry, _check_declarations, _check_analyses, _check_actions
# and _check_plans. So an analysis whose evaluator no longer matches its declared `emits`, or a
# proposer with no plan, becomes a BUILD failure rather than a 04:00 one. There is no CI in this
# repo, so this line is the closest thing to it that exists.
RUN python -c "import synapse.orchestrator.__main__"

# Non-root. The sweep writes no local filesystem: it reads Postgres and writes Postgres.
RUN useradd --system --no-create-home synapse
USER synapse

# ENTRYPOINT, not CMD. Cloud Run's --args replaces ARGS (docker CMD) and leaves COMMAND (docker
# ENTRYPOINT) intact, so an execution passes only what it wants to vary. With CMD, every
# hand-run would have to re-supply `python,-m,synapse.orchestrator`. No EXPOSE: a job serves
# nothing.
ENTRYPOINT ["python", "-m", "synapse.orchestrator"]
