# Step 6.1 — Dockerize for GCP Dev Server

## Context and intent

Phase 5 closed. Build is at demo-perfect state. Time to ship it to a stable URL on GCP so demos don't depend on running `pnpm dev` locally.

User has provisioned GCP infrastructure via Terraform. Frontend lives on Cloud Run v2 in asia-south1, project `ithina-retail-admin`. Cloud Run service `admin-frontend` is already deployed with placeholder image `gcr.io/cloudrun/hello`. Artifact Registry repo `admin-images` exists. Real image rolls in via `gcloud run deploy --image=...` (Terraform's lifecycle.ignore_changes block tolerates the drift).

This step builds the Dockerfile + deploy script + supporting config to ship the current `main` branch as a working hosted dev URL.

**Three confirmed decisions:**

1. **MSW stays in the deployed image.** Forced on at build time via `NEXT_PUBLIC_USE_MOCKS=true` Docker build-arg. Replaces the current `process.env.NODE_ENV === "development"` gate. Demo runs against stable mocks; doesn't depend on Sanjeev's backend being up. Forward-compatible with Phase 4b wiring (flip the build-arg to false, real backend integration begins).

2. **Persona switcher stays.** Auth0 secrets are already wired in Terraform (server-side env vars from Secret Manager) but the frontend continues using the persona switcher + RS256 JWT proxy. Real auth wiring is a separate future step. Auth0 secrets present in the runtime environment but unused.

3. **Local `deploy-dev.sh` script** rather than Cloud Build automation. Solo dev, faster iteration. Cloud Build can come later if the team grows.

## Out of scope

- Real auth (Auth0/NextAuth integration) — separate future step
- Phase 4b backend wiring — blocked on Sanjeev's deployed reads
- Cloud Build / GitHub Actions automation — explicitly deferred
- Production environment (different terraform module: `envs/prod/` with GKE, not Cloud Run) — not in scope
- Custom domain / load balancer — Cloud Run default `*.run.app` URL is fine for dev
- Health check endpoint design — Cloud Run does HTTP probes on `/`; current frontend responds OK on `/` (auth redirect or login screen, both 200), so existing behavior is enough

## Concrete GCP values from Terraform

These go into the Dockerfile and deploy script as known constants, not variables:

- **Project ID:** `ithina-retail-admin`
- **Region:** `asia-south1`
- **Cloud Run service name:** `admin-frontend`
- **Artifact Registry repository:** `admin-images`
- **Full image path prefix:** `asia-south1-docker.pkg.dev/ithina-retail-admin/admin-images/admin-frontend`
- **Container port:** `3000` (matches Terraform's `container_port = 3000`)
- **Service account:** `admin-frontend@ithina-retail-admin.iam.gserviceaccount.com` (provisioned by Terraform; deploy script doesn't manage this)
- **Resource limits (info only):** 1 vCPU, 512Mi memory, scale-to-zero, max 5 instances

## Acceptance criteria

1. **Multi-stage `Dockerfile`** at repo root. Stages:
   - `deps`: Node 22 alpine, pnpm via corepack, install with `--frozen-lockfile`
   - `builder`: copy source, run `pnpm build` with `NEXT_PUBLIC_USE_MOCKS` and any other build-time env vars passed as ARGs
   - `runner`: minimal node 22 alpine, copy `.next/standalone` + `.next/static` + `public/`, run `node server.js` on port 3000

2. **`next.config.ts` updated to `output: 'standalone'`.** Required for the runner stage to work — emits a self-contained `server.js` with only the dependencies actually used. Without this, the runner stage either copies all of `node_modules` (huge image) or breaks at runtime (missing deps).

3. **MSW gate change.** In whichever file boots MSW (likely `app/providers.tsx`'s `useEffect` for the mock worker, or a separate `lib/mocks/init.ts`):
   - **Before:** check is `process.env.NODE_ENV !== "production"` (or similar dev-only gate)
   - **After:** check is `process.env.NEXT_PUBLIC_USE_MOCKS === "true"`

   Verify both dev and prod-with-build-arg paths boot MSW. Verify prod-without-build-arg does NOT boot MSW (so the eventual Phase 4b wiring works by flipping one flag).

4. **`.dockerignore`** at repo root. Excludes: `.next`, `node_modules`, `.git`, `.env*` (except `.env.example`), `*.md`, `prompts/`, `Docs/`, anything else not needed in the build context. Keep build context small.

5. **`deploy-dev.sh`** at repo root (or `scripts/deploy-dev.sh` if Claude Code prefers a scripts folder). Bash script that:
   - Validates prereqs: `gcloud` authenticated, project set to `ithina-retail-admin`, current branch is clean (no uncommitted changes — refuse to deploy dirty state)
   - Computes image tag from `git rev-parse --short HEAD` (e.g., `abc1234`)
   - Builds with `docker build --build-arg NEXT_PUBLIC_USE_MOCKS=true -t <full-image-path>:<tag> -t <full-image-path>:latest .`
   - Pushes both tags to Artifact Registry
   - Calls `gcloud run deploy admin-frontend --image=<full-image-path>:<tag> --region=asia-south1`
   - On success: echoes the resulting `*.run.app` URL
   - On failure: clear error message, non-zero exit code

6. **`README.md` deploy section** (or new `DEPLOY.md` if cleaner). Documents:
   - Prerequisites (one-time): `gcloud auth login`, `gcloud auth configure-docker asia-south1-docker.pkg.dev`, project set
   - Per-deploy: `./deploy-dev.sh`
   - How to roll back: `gcloud run revisions list --service=admin-frontend --region=asia-south1` then `gcloud run services update-traffic admin-frontend --to-revisions=<rev>=100 --region=asia-south1`
   - How to view logs: `gcloud run services logs read admin-frontend --region=asia-south1 --limit=50`

7. **Local Docker test.** Build image locally with `docker build`, run with `docker run -p 3000:3000 -e PORT=3000 <image>`, verify the dashboard loads at `localhost:3000`. Persona switcher works. Tenant page renders mocked data. This is the smoke gate before deploying.

8. **Deploy smoke test.** After running `./deploy-dev.sh`, hit the resulting `*.run.app` URL in a browser. Verify:
   - Dashboard loads
   - Persona switcher works
   - Tenants page renders 7 tenants
   - Light/dark theme toggle works
   - No console errors (modulo the activation race we've been carrying)

9. `pnpm tsc --noEmit` exits zero (no regressions from the MSW gate change).
10. `pnpm lint` exits zero.
11. `pnpm build` succeeds locally with the build-arg toggle (verify both paths: with `NEXT_PUBLIC_USE_MOCKS=true` and without).
12. BUILD_PLAN.md updated: Step 6.1 → DONE; Phase 6 (deploy infrastructure) introduced as a new top-level phase if not already.
13. PATTERNS.md updated with "Deploy flow" section: how the build-arg toggle works, when to flip MSW off, how to roll back.

## Dockerfile specifics

Some Next.js + Docker quirks to handle correctly:

### Standalone output requires a specific copy pattern

Next.js standalone mode emits `.next/standalone/` containing `server.js` and a minimal subset of `node_modules`. But it does NOT include `.next/static/` or `public/`. The runner stage must copy all three:

```dockerfile
COPY --from=builder --chown=nextjs:nodejs /app/.next/standalone ./
COPY --from=builder --chown=nextjs:nodejs /app/.next/static ./.next/static
COPY --from=builder --chown=nextjs:nodejs /app/public ./public
```

The `./` destination in the first line is intentional — standalone is meant to be the root of the runtime filesystem.

### Non-root user

Cloud Run runs containers as non-root by default. Add a `nextjs` user in the runner stage:

```dockerfile
RUN addgroup --system --gid 1001 nodejs && \
    adduser --system --uid 1001 nextjs
USER nextjs
```

### Build-time vs runtime env vars

`NEXT_PUBLIC_*` vars must be set at build time because Next.js inlines them into the bundle. Pass via `ARG`:

```dockerfile
ARG NEXT_PUBLIC_USE_MOCKS=false
ENV NEXT_PUBLIC_USE_MOCKS=$NEXT_PUBLIC_USE_MOCKS
```

The deploy script passes `--build-arg NEXT_PUBLIC_USE_MOCKS=true`. Default is `false` so that someone running `docker build` without args gets the no-MSW build.

`PORT` is set at runtime; don't bake into the image. Cloud Run sets it via the service config (Terraform sets `container_port = 3000` which Cloud Run translates to `PORT=3000` env).

### pnpm in alpine

pnpm via corepack:

```dockerfile
RUN corepack enable && corepack prepare pnpm@<version> --activate
```

Pin the pnpm version to whatever's in `package.json`'s `packageManager` field. If that field doesn't exist, add it.

### Image size target

Standalone Next.js + node:22-alpine should land around 150-200MB. If the runner image is over 400MB, something's wrong (probably copying full `node_modules` instead of standalone's subset). Verify with `docker images` after build.

## `deploy-dev.sh` specifics

```bash
#!/usr/bin/env bash
set -euo pipefail

# Constants
PROJECT_ID="ithina-retail-admin"
REGION="asia-south1"
SERVICE="admin-frontend"
REGISTRY="asia-south1-docker.pkg.dev"
REPO="admin-images"
IMAGE_NAME="admin-frontend"
IMAGE_BASE="${REGISTRY}/${PROJECT_ID}/${REPO}/${IMAGE_NAME}"

# Validate
[[ "$(gcloud config get-value project 2>/dev/null)" == "$PROJECT_ID" ]] || {
  echo "ERROR: gcloud project is not $PROJECT_ID. Run: gcloud config set project $PROJECT_ID"
  exit 1
}

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: Working tree has uncommitted changes. Commit or stash first."
  git status --short
  exit 1
fi

# Tag from git SHA
SHA="$(git rev-parse --short HEAD)"
TAG="${IMAGE_BASE}:${SHA}"
LATEST="${IMAGE_BASE}:latest"

echo ">> Building image $TAG"
docker build \
  --build-arg NEXT_PUBLIC_USE_MOCKS=true \
  -t "$TAG" \
  -t "$LATEST" \
  .

echo ">> Pushing to Artifact Registry"
docker push "$TAG"
docker push "$LATEST"

echo ">> Deploying to Cloud Run"
gcloud run deploy "$SERVICE" \
  --image="$TAG" \
  --region="$REGION" \
  --project="$PROJECT_ID"

URL="$(gcloud run services describe "$SERVICE" --region="$REGION" --project="$PROJECT_ID" --format='value(status.url)')"
echo ""
echo "Deployed: $URL"
echo "Image: $TAG"
```

Make sure to `chmod +x deploy-dev.sh` after creation.

## Files modified

New:
- `Dockerfile` — multi-stage build
- `.dockerignore` — exclude unnecessary build context
- `deploy-dev.sh` — local deploy script (chmod +x)
- `DEPLOY.md` (or section in README.md) — deploy documentation

Modified:
- `next.config.ts` — add `output: 'standalone'`
- `app/providers.tsx` (or wherever MSW boots) — change gate to `NEXT_PUBLIC_USE_MOCKS === "true"`
- `package.json` — verify `packageManager` field is set; add if missing
- `BUILD_PLAN.md` — Step 6.1 → DONE; Phase 6 introduced
- `PATTERNS.md` — "Deploy flow" section

Untouched:
- All other application code
- All terraform (lives in a separate repo presumably; not this build's concern)

Estimated diff: 6-8 files. Concentrated in Dockerfile + deploy script + the small MSW gate change.

## Smoke checklist

Pre-deploy (local Docker):

1. `pnpm build` succeeds locally without build-arg (no MSW). Open the built app via `pnpm start` — verify MSW does NOT boot. Provision Tenant should fail (no backend), confirming MSW is truly off.
2. `docker build --build-arg NEXT_PUBLIC_USE_MOCKS=true -t admin-frontend:test .` succeeds. Verify image size is under 250MB via `docker images`.
3. `docker run -p 3000:3000 -e PORT=3000 admin-frontend:test` runs. App accessible at localhost:3000. Persona switcher works. Tenants page shows mocked data.
4. `docker run -p 3000:3000 -e PORT=3000 admin-frontend:test` (no build-arg this time, image rebuilt without): Tenants page should error/empty (no MSW, no backend). Confirms the gate works correctly in both directions.

Deploy:

5. Run `./deploy-dev.sh`. Watch the build, push, deploy stages. Should complete in 5-8 minutes total (most of it is the build).
6. Resulting URL printed at the end. Open it.
7. Dashboard loads. Persona switcher works. Tenants renders 7 tenants. Light/dark theme works.
8. Check Cloud Run logs: `gcloud run services logs read admin-frontend --region=asia-south1 --limit=20`. No errors visible.

Post-deploy:

9. Verify the URL is the same one Terraform output (the one CORS is wired against).
10. Confirm the Cloud Run service shows the new image: `gcloud run services describe admin-frontend --region=asia-south1 --format="value(spec.template.spec.containers[0].image)"`.

## Process notes

- This step touches the most production-adjacent surface in the build so far. Test locally before deploying. Skipping local verification means a broken deploy and a 5-minute cycle to redo it.
- The MSW gate change is a tiny edit but it's the one thing that's easy to get wrong. Double-check both paths work: `pnpm dev` still boots MSW (legacy dev experience preserved), `docker build` with build-arg boots MSW, `docker build` without build-arg does NOT boot MSW.
- If `pnpm dev` breaks because the gate change removed the dev-mode trigger, add a fallback: `process.env.NEXT_PUBLIC_USE_MOCKS === "true" || process.env.NODE_ENV === "development"`. This preserves the old dev experience while enabling the prod-with-mocks build.
- The first deploy will be slower than subsequent ones because Docker has no layer cache. ~8 minutes total. Subsequent deploys with small changes ~3 minutes.
- If `gcloud run deploy` fails, common causes: image not pushed (network issue), service account missing IAM permissions, image architecture mismatch (build on Apple Silicon, deploy to amd64 — fix with `docker buildx build --platform linux/amd64`).
- Cloud Run cold-start: with min_instances=0, the first request after idle takes ~3-5 seconds to spin up. Acceptable for a dev demo URL. If demo audience finds this rough, bump min_instances to 1 in Terraform later.

## Ask before building

Things worth surfacing upfront:

- **`packageManager` field in package.json.** Confirm what's there. If absent, what version of pnpm is the user running locally (`pnpm --version`)? Need to pin in the Dockerfile.
- **Current MSW boot location.** Where exactly does MSW initialize? `app/providers.tsx` is most likely but verify. Need to know the exact gate to change.
- **Apple Silicon developer machine?** If the user runs Docker on an arm64 Mac, building without `--platform linux/amd64` produces an arm64 image that Cloud Run can't run. Need to add the platform flag to the build command if so.
- **Image architecture decision.** Cloud Run supports both amd64 and arm64 (recently). amd64 is the safer default for now. Confirm before locking in.
- **`output: 'standalone'` compatibility.** Next.js 16 supports standalone but verify nothing in the codebase depends on a non-standalone runtime (rare but possible — typically things that read from the filesystem at runtime expecting `node_modules` to be present in the typical place).
- **Existing `.gitignore` vs `.dockerignore` overlap.** Most things in `.gitignore` should also be in `.dockerignore`, but `.dockerignore` should additionally exclude things that ARE in git but aren't needed in the image (`Docs/`, `prompts/`, `*.md`, etc.).

Post the pre-smoke self-check structured table when ready, same shape as v0 + 4.1 + 5.1.x + 5.2.x steps. Smoke this one carefully — pre-deploy local test (steps 1-4 in the smoke checklist) before running `./deploy-dev.sh`. After full smoke passes, propose the commit. Expected commit message:

> Step 6.1: Dockerize for GCP dev server
>
> Multi-stage Dockerfile (Node 22 alpine, standalone Next.js output). MSW gate moved from NODE_ENV check to NEXT_PUBLIC_USE_MOCKS build-arg toggle (default false; deploy script passes true to bake mocks into dev image). Local deploy-dev.sh script handles build → push to Artifact Registry → gcloud run deploy.
>
> Targets: Cloud Run v2 service `admin-frontend` in asia-south1, project ithina-retail-admin. Pre-existing Terraform-provisioned infrastructure (lifecycle.ignore_changes on image field tolerates deploy-driven image rolls).
>
> Forward-compatible with Phase 4b: flipping NEXT_PUBLIC_USE_MOCKS to false at build time switches the deployed frontend to call Sanjeev's real backend. CORS already wired in Terraform.
