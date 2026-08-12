# axon-sender - Axon's poll loop over axon-send-requested, run as a Cloud Run SERVICE.
#
# A THIRD DOCKERFILE RATHER THAN A PARAMETERISED ONE, on the same three grounds
# synapse/services/synapse-ui-server/Dockerfile records:
#   1. This is duplicated BOILERPLATE, not duplicated behaviour. A base image line
#      cannot disagree about what it computes; it can only go stale, and staleness
#      is visible in a diff.
#   2. Exec-form ENTRYPOINT cannot interpolate an ARG.
#   3. COPY cannot be conditional, and the closures genuinely differ.
#
# WHAT MUST MOVE TOGETHER with the other two, since it is shared and can go stale:
# the python base tag, the uv tag, and the dis workspace skeleton COPY.
#
# THE COPY SET IS RESOLVED, NOT GUESSED. `uv tree --package axon-sender` reaches:
#
#   thalamus-axon   the envelope, the Channel port, the SendGrid adapter, the
#                   ledger and the send path. Every piece of behaviour this
#                   service has is Axon's; the service is a loop around it.
#   dis-rls         the two-GUC session discipline and the first-use posture guard
#   dis-core        the JSON logger that emits `severity`
#   axon-sender     itself
#
# NO thalamus-synapse AND NO dis-canonical. This service never reads a canonical
# row and knows nothing about analyses; the sender does not import Synapse and
# must not start to.
#
# THE BUILD CONTEXT IS THE MONOREPO ROOT. The uv workspace is rooted at dis/ and
# declares axon and this service as ../-relative siblings, so a dis/-rooted
# context cannot reach them.
#
# Canonical build command (run from the monorepo root):
#
#   docker build -f axon/services/axon-sender/Dockerfile -t axon-sender .

FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.11 /uv /uvx /bin/

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

WORKDIR /app

# AXON, at /axon so the workspace's ../axon and ../axon/services/axon-sender
# member sources resolve. The whole directory, alembic chain and DDL included, for
# the same reason synapse-ui-server copies it: one image, not two.
COPY axon /axon

# The dis workspace skeleton: root project plus the two libs this closure reaches.
# dis-canonical is absent and its absence is checked by the build below failing if
# anything starts importing it.
COPY dis/pyproject.toml dis/uv.lock ./
COPY dis/libs/dis-core /app/libs/dis-core
COPY dis/libs/dis-rls /app/libs/dis-rls

# SYNAPSE'S SOURCES ARE COPIED AND NOT INSTALLED. `uv sync --frozen` resolves the
# whole workspace's member list even when installing one package, so a member
# named in dis/pyproject.toml whose source is absent fails the sync. Copying the
# pyproject files alone satisfies the resolver without pulling FastAPI, uvicorn or
# pyjwt into this image: --package axon-sender is what keeps the install narrow.
COPY synapse/pyproject.toml /synapse/pyproject.toml
COPY synapse/services/synapse-ui-server/pyproject.toml /synapse/services/synapse-ui-server/pyproject.toml
COPY dis/libs/dis-canonical/pyproject.toml /app/libs/dis-canonical/pyproject.toml

RUN uv sync --frozen --no-dev --package axon-sender

ENV PATH="/app/.venv/bin:$PATH"

# THE TARGET, DECLARED ONCE. The build-time check below and the CMD at the bottom
# both read this variable, so the string python resolves at startup is literally
# the string the build verified.
#
# WRITING IT TWICE SHIPPED A BROKEN IMAGE ONCE, on synapse-ui-server: the CMD said
# `main:app` while the check imported `create_app`, the check passed and the
# container died on startup. One copy was checked and the other shipped.
ENV ENTRY_MODULE="axon_sender.main"

# RESOLVE THE ENTRY MODULE AND ASSERT ITS SHAPE, at build time.
#
# NO FACTORY CALL HERE, unlike synapse-ui-server's check. That service builds a
# FastAPI app whose routes are worth asserting; this one builds an engine, a
# provider client and a Pub/Sub subscriber, all of which need real credentials and
# a real subscription. So what is checked is what CAN be checked offline: the
# module imports, `main` exists and is callable, and the config loader REFUSES an
# empty environment. That last one is the useful half: it proves the boot-time
# guard is wired, which is what stops a misconfigured revision pulling messages it
# cannot send and nacking them until they dead-letter.
#
# THE ENV LIST IS PART OF THE CONTRACT AND MUST TRACK load_config(). v6 and v15 of
# synapse-ui-server both failed at exactly this step because a variable was added
# to a loader and not here. This check inverts that: it asserts the loader REFUSES
# a bare environment and NAMES every variable, so adding one to the loader cannot
# make this check stale.
RUN python -c "\
import os, importlib; \
module = importlib.import_module(os.environ['ENTRY_MODULE']); \
assert callable(getattr(module, 'main', None)), 'axon_sender.main.main is not callable'; \
config = importlib.import_module('axon_sender.config'); \
required = ['GOOGLE_CLOUD_PROJECT', 'AXON_SENDER_URL', 'AXON_SENDGRID_API_KEY', 'AXON_SENDGRID_FROM_EMAIL']; \
raised = None; \
exec('try:\n config.load_config()\nexcept RuntimeError as exc:\n raised = str(exc)'); \
assert raised is not None, 'load_config accepted an empty environment; the boot guard is not wired'; \
missing = [name for name in required if name not in raised]; \
assert not missing, f'load_config did not name {missing} as missing; the message is what an operator reads'; \
print(f\"{os.environ['ENTRY_MODULE']} imports and refuses an empty environment naming {len(required)} variables\")"

# Non-root. The service writes no local filesystem: it reads a queue, calls a
# provider and writes Postgres.
RUN useradd --system --no-create-home axonsender
USER axonsender

# The health server binds $PORT; Cloud Run injects it.
EXPOSE 8080

# SHELL FORM WITH `exec`, and it is the same reasoning as synapse-ui-server's CMD.
# Cloud Run sets $PORT and the config reads it, so nothing here needs to expand a
# variable, but `exec` is what puts python at PID 1 so SIGTERM reaches it directly.
# Without it the shell holds PID 1, swallows the signal, and Cloud Run kills the
# container after the grace period instead of letting the loop finish its pass.
CMD exec python -m axon_sender.main
