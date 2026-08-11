# synapse-ui-server — Synapse's BFF, run as a Cloud Run SERVICE.
#
# READ-ONLY UNTIL SLICE 5d, and nearly so still: every GET reads through
# synapse_reader, and the two POSTs write one table each through a role that can do
# nothing else. synapse_lifecycle appends to synapse.action_events (5d);
# synapse_provisioner inserts into synapse.provision (5e) and holds no UPDATE, so the
# console cannot disable a tenant or edit a timezone.
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
# resolves clean, and the app object builds with EVERY route registered — checked by
# (path, method) rather than path alone, so the one write endpoint cannot register as
# a GET and still pass. The set was seven routes when this was written and has drifted
# twice since; it is now enumerated in full below rather than sampled.
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

# AXON, at /axon so the workspace's ../axon member source resolves. Slice 1 makes this
# service Axon's first PRODUCER, so axon joins the closure the same way thalamus-synapse
# already has. `uv tree --package synapse-ui-server` now reaches six workspace members
# rather than five; a missing source here fails `uv sync --frozen` at build time, which is
# the intended place to find out.
#
# THE ALEMBIC CHAIN AND THE DDL COME WITH IT, deliberately: this image is also what
# migrate-axon runs, exactly as the orchestrator's image is what migrate-synapse runs. That
# is migrate-cm's D6 argument (one image, not two) applied a third time, and it is why the
# COPY is the whole axon/ directory rather than axon/src alone.
COPY axon /axon

# The dis workspace skeleton: root project plus the three libs this closure reaches.
COPY dis/pyproject.toml dis/uv.lock ./
COPY dis/libs/dis-core /app/libs/dis-core
COPY dis/libs/dis-canonical /app/libs/dis-canonical
COPY dis/libs/dis-rls /app/libs/dis-rls

RUN uv sync --frozen --no-dev --package synapse-ui-server

ENV PATH="/app/.venv/bin:$PATH"

# THE ASGI TARGET, DECLARED ONCE. The build-time check below and the CMD at the
# bottom both read this variable, so the string uvicorn resolves at startup is
# literally the string the build verified.
#
# IT WAS WRITTEN TWICE AND THAT SHIPPED A BROKEN IMAGE. The CMD said
# `synapse_ui_server.main:app` while the check imported `create_app` — two
# different attributes of the same module. The check passed (create_app exists,
# builds, registers its routes) and the container then died on
# `Attribute "app" not found in module "synapse_ui_server.main"`. One copy was
# checked and the other shipped, which is the duplication class this project
# keeps paying for.
#
# `:create_app` with `--factory`, not `:app`: a module-level app would have to
# call load_config() at IMPORT time, which needs the runtime env and so cannot be
# built here. The factory defers that to startup, where the env exists.
ENV ASGI_TARGET="synapse_ui_server.main:create_app"

# RESOLVE $ASGI_TARGET EXACTLY AS UVICORN WILL, THEN CALL IT EXACTLY AS --factory
# WILL, AND ASSERT THE ROUTES.
#
# `uvicorn.importer.import_from_string` is uvicorn's OWN resolver, not a
# reimplementation of it — the previous check hand-rolled an import of a
# different attribute and that is precisely how the mismatch survived. Using the
# real function against the real string means the only way this passes and
# startup fails is a uvicorn bug.
#
# The dummy env exists because --factory calls create_app() with NO arguments, so
# it goes through load_config(); these values are build-time only, are never
# persisted into the image, and are syntactically valid rather than reachable.
# Cloud Run supplies the real ones.
#
# Calling the factory also executes every @app.get decorator, so a route that
# fails to register is a BUILD failure rather than a revision that starts, passes
# its health check and 404s the console — and it runs synapse.registry's
# import-time invariants, so a declaration whose evaluator no longer matches its
# `emits` fails here too.
# THE ENV LIST IS PART OF THE CONTRACT AND MUST TRACK load_config(). v6 failed here:
# slice 5d made SYNAPSE_LIFECYCLE_URL required and this list still held the pre-5d
# three, so the startup guard fired — correctly — during the build. The guard was
# right and the check was stale. A variable added to load_config() must be added
# here in the same commit, or the next build fails at step 15 instead of the review.
#
# SLICE 5e ADDED TWO MORE, both required and both here in the same commit as the
# load_config change that demands them: SYNAPSE_PROVISION_URL (the synapse_provisioner
# DSN) and CM_API_BASE_URL (Customer Master's origin, which the provisioning gate
# calls). CM_API_BASE_URL is deliberately unreachable at build time for the same
# reason the DSNs are: it is syntactically valid and nothing dials it here.
#
# SYNAPSE_WRITER_URL IS DELIBERATELY ABSENT and must stay absent: load_config refuses
# to start when it is set, because that is the ORCHESTRATOR's credential. Setting it
# here to "make the check pass" would break every real revision.
RUN SYNAPSE_READER_URL="postgresql+psycopg://u@h/d" \
    SYNAPSE_LIFECYCLE_URL="postgresql+psycopg://l@h/d" \
    SYNAPSE_PROVISION_URL="postgresql+psycopg://p@h/d" \
    CM_API_BASE_URL="https://build.invalid" \
    SYNAPSE_JWT_ISSUER="https://build.invalid/" \
    SYNAPSE_JWT_AUDIENCE="build-check" \
    AXON_SENDER_URL="postgresql+psycopg://a@h/d" \
    AXON_SENDGRID_API_KEY="build-check" \
    AXON_SENDGRID_FROM_EMAIL="noreply@build.invalid" \
    AXON_PLATFORM_ONCALL_EMAIL="oncall@build.invalid" \
    python -c "\
import os; \
from uvicorn.importer import import_from_string; \
target = os.environ['ASGI_TARGET']; \
factory = import_from_string(target); \
app = factory(); \
routes = {(r.path, m) for r in app.routes if hasattr(r, 'path') for m in (getattr(r, 'methods', None) or {'GET'})}; \
required = { \
    ('/healthz', 'GET'), ('/readyz', 'GET'), ('/fleet', 'GET'), ('/runs', 'GET'), \
    ('/capabilities', 'GET'), ('/analyses', 'GET'), ('/timezones', 'GET'), \
    ('/tenants/{tenant_id}', 'GET'), ('/tenants/{tenant_id}/runs', 'GET'), \
    ('/tenants/{tenant_id}/alerts', 'GET'), \
    ('/tenants/{tenant_id}/alerts/{event_id}', 'GET'), \
    ('/tenants/{tenant_id}/alerts/{event_id}/decisions', 'POST'), \
    ('/tenants/{tenant_id}/analyses/{analysis_id}/enable', 'POST'), \
}; \
missing = required - routes; \
assert not missing, f'routes did not register: {sorted(missing)}'; \
print(f'{target} resolves and builds {len(required)} routes')"

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
CMD exec uvicorn "$ASGI_TARGET" --factory --host 0.0.0.0 --port ${PORT:-8080}
