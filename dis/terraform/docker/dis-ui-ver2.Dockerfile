# syntax=docker/dockerfile:1.7
# dis-ui-ver2 (frontend, parallel to dis-ui)
#
# Builds the Vite SPA and serves the static assets with nginx, with SPA
# fallback (all routes -> index.html) so client-side routing works. Cloud Run
# serves this container. Mirrors terraform/docker/dis-ui.Dockerfile; the only
# differences are the image/service name (dis-ui-ver2) and the build context
# (services/dis-ui-ver2).
#
# BUILD-TIME vars (Vite bakes import.meta.env.VITE_* into the static JS at build,
# NOT at runtime). The UI reads exactly ONE mode var, so it MUST be passed as a build
# arg and baked here; a runtime Cloud Run env var does nothing for an already-built SPA:
#   VITE_DIS_UI_SERVER_MODE      'real' calls dis-ui-server; anything else is fixtures.
# The mode defaults to 'fixture' so a plain, un-parameterized build is never
# accidentally broken-real.
#
# The dis-ui-server base URL is NOT a build var: the SPA calls same-origin "/api/..." and
# nginx proxies /api to the backend, so the URL is a RUNTIME env (DIS_UI_SERVER_BASE_URL)
# on the serving container, envsubst'd into the nginx config at container start.
#
# Build from services/dis-ui-ver2 (the frontend package root):
#   docker build -f ../../docker/dis-ui-ver2.Dockerfile \
#     --build-arg VITE_DIS_UI_SERVER_MODE=real \
#     -t IMAGE .

# Node 22 to MATCH the dev/CI node (see .nvmrc). The Vite/rollup output hash is
# node-version-sensitive: building on a different major produces a DIFFERENT
# index-<hash>.js for byte-identical source. Pinning the build node to dev's node makes
# the production bundle hash reproducible with local builds.
FROM node:22-slim AS build
WORKDIR /app

# pnpm (the repo uses pnpm for the UI).
RUN corepack enable && corepack prepare pnpm@9.15.9 --activate

COPY package.json pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile

COPY . .

# Build-time Vite vars (ARG -> ENV -> baked by `vite build`). Mode defaults to
# 'fixture' (safe); staging passes 'real' via cloudbuild substitutions.
# VITE_STUB_TOKEN_TENANT / VITE_STUB_TOKEN_OPS / VITE_STUB_TOKEN_TENANT2 are the pre-supplied
# dev-login persona tokens (staging only); pass via .env.local or build-arg, never committed.
ARG VITE_DIS_UI_SERVER_MODE="fixture"
ARG VITE_STUB_TOKEN_TENANT=""
ARG VITE_STUB_TOKEN_OPS=""
ARG VITE_STUB_TOKEN_TENANT2=""
ENV VITE_DIS_UI_SERVER_MODE=${VITE_DIS_UI_SERVER_MODE}
ENV VITE_STUB_TOKEN_TENANT=${VITE_STUB_TOKEN_TENANT}
ENV VITE_STUB_TOKEN_OPS=${VITE_STUB_TOKEN_OPS}
ENV VITE_STUB_TOKEN_TENANT2=${VITE_STUB_TOKEN_TENANT2}
# Auth0 SPA config (real mode). Public PKCE client, so no secret is baked; these
# are safe build args inlined into the static bundle by vite build. Empty defaults
# keep a plain (fixture) build working; staging passes real values via cloudbuild.
ARG VITE_AUTH0_DOMAIN=""
ARG VITE_AUTH0_CLIENT_ID=""
ARG VITE_AUTH0_AUDIENCE=""
ENV VITE_AUTH0_DOMAIN=${VITE_AUTH0_DOMAIN}
ENV VITE_AUTH0_CLIENT_ID=${VITE_AUTH0_CLIENT_ID}
ENV VITE_AUTH0_AUDIENCE=${VITE_AUTH0_AUDIENCE}
# Single login entry point: DIS with no session redirects here (Customer Master's
# login, which lands on My Cortex) instead of running its own interactive login.
# Empty default keeps a plain build working; staging passes the real CM URL.
ARG VITE_CM_LOGIN_URL=""
ENV VITE_CM_LOGIN_URL=${VITE_CM_LOGIN_URL}
RUN pnpm build

# --- serve ---
FROM nginx:1.27-alpine AS serve

# Backend URL is a RUNTIME env var. envsubst-on-templates rewrites
# ${DIS_UI_SERVER_BASE_URL} into a literal at container start (before nginx boots), so
# no resolver directive is needed. The filter restricts substitution to DIS_UI_* so
# nginx runtime vars ($uri, $proxy_host, $scheme) are preserved.
ENV NGINX_ENVSUBST_FILTER=^DIS_UI_

# Fail loud, before nginx starts, if the backend URL is missing. Named 15- so it runs
# BEFORE 20-envsubst-on-templates.sh.
COPY <<'SH' /docker-entrypoint.d/15-check-dis-base-url.sh
#!/bin/sh
set -e
if [ -z "$DIS_UI_SERVER_BASE_URL" ]; then
  echo "FATAL: DIS_UI_SERVER_BASE_URL is not set; dis-ui-ver2 cannot proxy /api to dis-ui-server." >&2
  exit 1
fi
SH
RUN chmod +x /docker-entrypoint.d/15-check-dis-base-url.sh

COPY <<'NGINX' /etc/nginx/templates/default.conf.template
server {
    client_max_body_size 11m;
  listen       8080;
  server_name  _;
  root   /usr/share/nginx/html;
  index  index.html;

  location /api/ {
    proxy_pass               ${DIS_UI_SERVER_BASE_URL};
    proxy_http_version       1.1;
    proxy_ssl_server_name    on;
    proxy_set_header Host              $proxy_host;
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
  }

  location / {
    try_files $uri $uri/ /index.html;
  }
}
NGINX

COPY --from=build /app/dist /usr/share/nginx/html
EXPOSE 8080
CMD ["nginx", "-g", "daemon off;"]
