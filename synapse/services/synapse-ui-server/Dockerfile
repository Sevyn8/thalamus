# synapse-ui-server — Synapse's read-only BFF, run as a Cloud Run SERVICE.
#
# A SECOND DOCKERFILE RATHER THAN A PARAMETERISED ONE, and the reasoning matters
# because this project has paid three times for duplication (the Pub/Sub poll
# loop, mint_connector_run_id, the canonical ORM):
#
#   1. THIS IS DUPLICATED BOILERPLATE, NOT DUPLICATED BEHAVIOUR. Those three cases
#      were duplicated LOGIC — two copies that could disagree about what they
#      compute, where the copy that drifts is the one nobody is looking at. A base
#      image line cannot disagree about behaviour. It can only go stale, and
#      staleness is visible in a diff.
#   2. EXEC-FORM ENTRYPOINT CANNOT INTERPOLATE AN ARG. Parameterising the start
#      command forces shell form, which breaks the ENTRYPOINT/CMD split the
#      orchestrator relies on for `gcloud run jobs execute --args`, and puts a
#      shell at PID 1 where signals go to the wrong process.
#   3. COPY CANNOT BE CONDITIONAL. The two closures genuinely differ and the
#      difference is expressed in COPY lines.
#
# A multi-stage file with two `--target`s would work and was the real
# alternative. It was not taken because it means rewriting a working artifact
# that already produces a deployed image, to share about eight lines.
#
# WHAT MUST MOVE TOGETHER WITH synapse/Dockerfile, since it is shared and can go
# stale: the python base tag, the uv tag, and the dis workspace skeleton COPY
# (pyproject.toml, uv.lock, the three libs). The build-time import check at the
# bottom is what catches a skeleton that has drifted — a missing lib fails the
# build rather than the first request.
#
# THE COPY SET IS RESOLVED, NOT COPIED FROM THE ORCHESTRATOR AND EXTENDED.
# `uv tree --package synapse-ui-server` gives five workspace members:
#
#   thalamus-synapse   the registry, declarations and resolvers — the reason this
#                      service is Python at all: E1/E2 read object state, not rows
#   dis-canonical      canonical row shapes
#   dis-rls            the two-GUC session discipline and the target/role guard
#   dis-core           UUIDv7 and the JSON logger that emits `severity`
#   synapse-ui-server  itself
#
# Assembled in a scratch tree and verified with the real command: 37 packages,
# resolves clean, and the app object builds with all seven routes registered.
# (The orchestrator's image is 21 packages — FastAPI, uvicorn and pyjwt are the
# difference, and keeping them out of it is exactly why this is a separate
# workspace member.)
#
# THE BUILD CONTEXT IS THE MONOREPO ROOT. The uv workspace is rooted at dis/ and
# declares both synapse and this service as ../-relative siblings, so a dis/-rooted
# context cannot reach them.
#
# Canonical build command (run from the monorepo root):
#
#   docker build -f synapse/services/synapse-ui-server/Dockerfile -t synapse-ui-server .

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Synapse and its BFF, at /synapse so the workspace's ../synapse and
# ../synapse/services/synapse-ui-server member sources resolve.
COPY synapse/pyproject.toml /synapse/pyproject.toml
COPY synapse/src /synapse/src
COPY synapse/services/synapse-ui-server /synapse/services/synapse-ui-server

# The dis workspace skeleton: root project plus the three libs this closure reaches.
COPY dis/pyproject.toml dis/uv.lock ./
COPY dis/libs/dis-core /app/libs/dis-core
COPY dis/libs/dis-canonical /app/libs/dis-canonical
COPY dis/libs/dis-rls /app/libs/dis-rls

RUN uv sync --frozen --no-dev --package synapse-ui-server

ENV PATH="/app/.venv/bin:$PATH"

# BUILD THE APP OBJECT AT BUILD TIME, which is strictly stronger than importing
# the module.
#
# An import proves the graph resolves. CALLING create_app() additionally executes
# every @app.get decorator, so a route that fails to register — a bad path, a
# dependency that cannot be constructed, a duplicated operation id — becomes a
# BUILD failure rather than a revision that starts, passes its health check and
# 404s the console. dis-ui-server shipped precisely that once: green build, clean
# push, ModuleNotFoundError in the container.
#
# It also runs synapse.registry's import-time invariants (_check_registry,
# _check_declarations, _check_analyses, _check_actions, _check_plans, _check_windows),
# so a declaration whose evaluator no longer matches its `emits` fails here too.
#
# The Config is a throwaway with a syntactically valid DSN: create_app() must not
# touch a database, and this line is also what proves it doesn't.
RUN python -c "\
from synapse_ui_server.config import Config; \
from synapse_ui_server.main import create_app; \
app = create_app(Config(reader_url='postgresql+psycopg://u@h/d', jwt_issuer='https://x/', jwt_audience='a', expected_database='thalamus')); \
paths = {r.path for r in app.routes if hasattr(r, 'path')}; \
required = {'/healthz', '/readyz', '/fleet', '/tenants/{tenant_id}', '/runs', '/capabilities', '/analyses'}; \
missing = required - paths; \
assert not missing, f'routes did not register: {sorted(missing)}'; \
print(f'all {len(required)} routes registered')"

# Non-root. The service writes no local filesystem: it reads Postgres and returns JSON.
RUN useradd --system --no-create-home synapseui
USER synapseui

# UNLIKE THE ORCHESTRATOR, THIS ONE LISTENS. Three differences the image reflects:
# it serves a port, it exposes /healthz and /readyz, and Cloud Run injects PORT.
EXPOSE 8080

# SHELL FORM WITH `exec`, deliberately, and it is the opposite choice from the
# orchestrator's exec-form ENTRYPOINT.
#
# Cloud Run sets $PORT and a container that hardcodes a port fails to start when
# that value is not 8080. Exec form cannot expand an environment variable, so the
# port must come through a shell — and `exec` replaces that shell with uvicorn, so
# uvicorn is PID 1 and receives SIGTERM directly. Without `exec`, the shell holds
# PID 1, swallows the signal, and Cloud Run kills the container after the grace
# period instead of letting it drain.
#
# CMD rather than ENTRYPOINT because a service takes no per-execution arguments;
# the orchestrator uses ENTRYPOINT precisely so `--args` can vary a run.
CMD exec uvicorn synapse_ui_server.main:app --host 0.0.0.0 --port ${PORT:-8080}
