# syntax=docker/dockerfile:1
# Multi-stage build for Next.js standalone output. Targets Cloud Run v2.

FROM node:22-alpine AS deps
RUN corepack enable && corepack prepare pnpm@10.33.0 --activate
WORKDIR /app
COPY package.json pnpm-lock.yaml pnpm-workspace.yaml ./
RUN pnpm install --frozen-lockfile

FROM node:22-alpine AS builder
RUN corepack enable && corepack prepare pnpm@10.33.0 --activate
WORKDIR /app

# The API base URL, auth mode, and dev JWTs are now RUNTIME config, not
# build-time inlined NEXT_PUBLIC_* values. They are supplied as runtime
# env on the runner stage / Cloud Run service (API_BASE_URL, AUTH_MODE,
# DEV_JWT_MAP) and read server-side at request time, so the same image
# can be promoted across projects without a rebuild. Nothing
# build-output-affecting needs to be passed here before `pnpm build`.
ENV NEXT_TELEMETRY_DISABLED=1

COPY --from=deps /app/node_modules ./node_modules
COPY . .
RUN pnpm build

FROM node:22-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
# Runtime config (API_BASE_URL, AUTH_MODE, DEV_JWT_MAP) is injected by the
# deploy environment (terraform runtime_env / Cloud Run), not baked here.
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
USER nextjs
EXPOSE 3000
ENV PORT=3000
ENV HOSTNAME=0.0.0.0
CMD ["node", "server.js"]
