#!/usr/bin/env bash
# Local deploy script for the dev Cloud Run service.
#
# Auth model uses pre-minted JWTs (per Sanjeev's wiring handoff §3.2),
# not server-side RS256 mint. The script bakes the JWTs + the deployed-
# backend base URL into the image at `docker build` time as
# NEXT_PUBLIC_* build-args. Nothing auth-related flows through
# terraform's runtime_env.
#
# Phase 5n.1 (2026-05-18): MSW removed wholesale. NEXT_PUBLIC_USE_MOCKS
# build-arg dropped — the deployed image hits Sanjeev's real backend
# for every API call. Reads that don't have backend coverage yet
# surface as empty states (see BUILD_PLAN Finding #31).
#
# Phase 5n.1: JWTs sourced from Tests01/ (150-day cloud JWTs) instead
# of ~/.ithina-secrets/ (the prior 7-day JWTs had user_ids never seeded
# with grants in deployed backend; the 150-day user_ids align with
# fixtures and are seeded). Re-mint via Sanjeev when the 150-day expiry
# rolls and overwrite Tests01/.
set -euo pipefail

PROJECT_ID="ithina-dis-cm"
REGION="asia-south1"
SERVICE="admin-frontend"
REGISTRY="asia-south1-docker.pkg.dev"
REPO="admin-images"
IMAGE_NAME="admin-frontend"
IMAGE_BASE="${REGISTRY}/${PROJECT_ID}/${REPO}/${IMAGE_NAME}"

# Deployed backend that the image's NEXT_PUBLIC_API_BASE_URL points at.
# Hardcoded for the dev service; lift to a flag if/when prod lands.
BACKEND_URL="https://admin-backend-wx5tzvqiaa-el.a.run.app"

# JWT files baked into the deployed image. Repo-relative paths so the
# deploy is reproducible from a clean checkout.
ANJALI_JWT_FILE="Tests01/anjali-cloud-150d.jwt"
KOWALSKI_JWT_FILE="Tests01/a-kowalski-cloud-150d.jwt"

# --- Validate prereqs ------------------------------------------------

CURRENT_PROJECT="$(gcloud config get-value project 2>/dev/null || echo '')"
if [[ "$CURRENT_PROJECT" != "$PROJECT_ID" ]]; then
  echo "ERROR: gcloud project is '$CURRENT_PROJECT', expected '$PROJECT_ID'."
  echo "Run: gcloud config set project $PROJECT_ID"
  exit 1
fi

if [[ -n "$(git status --porcelain)" ]]; then
  echo "ERROR: Working tree has uncommitted changes. Commit or stash first."
  git status --short
  exit 1
fi

if [[ ! -f "$ANJALI_JWT_FILE" ]] || [[ ! -f "$KOWALSKI_JWT_FILE" ]]; then
  echo "ERROR: JWT files missing under Tests01/."
  echo "Expected:"
  echo "  $ANJALI_JWT_FILE"
  echo "  $KOWALSKI_JWT_FILE"
  echo "Re-mint via Sanjeev (150-day cloud JWTs against deployed-backend seed user_ids) and commit to Tests01/."
  exit 1
fi

ANJALI_JWT="$(cat "$ANJALI_JWT_FILE")"
KOWALSKI_JWT="$(cat "$KOWALSKI_JWT_FILE")"

if [[ -z "$ANJALI_JWT" ]] || [[ -z "$KOWALSKI_JWT" ]]; then
  echo "ERROR: One of the JWT files is empty."
  exit 1
fi

echo ">> Loaded JWTs (anjali: ${#ANJALI_JWT} chars, kowalski: ${#KOWALSKI_JWT} chars)"

# --- Tag from git SHA ------------------------------------------------

SHA="$(git rev-parse --short HEAD)"
TAG="${IMAGE_BASE}:${SHA}"
LATEST="${IMAGE_BASE}:latest"

# --- Build -----------------------------------------------------------

echo ">> Building image $TAG"
# NEXT_PUBLIC_DIS_ENABLED dropped in Phase 5i.3b — DIS surfaces archived to
# archive/dis-legacy/; DIS UI now lives in the ithina-dis monorepo per
# Sanjeev's D25/D26.
docker build \
  --build-arg "NEXT_PUBLIC_API_BASE_URL=$BACKEND_URL" \
  --build-arg "NEXT_PUBLIC_DEV_JWT_ANJALI=$ANJALI_JWT" \
  --build-arg "NEXT_PUBLIC_DEV_JWT_KOWALSKI=$KOWALSKI_JWT" \
  -t "$TAG" \
  -t "$LATEST" \
  .

# --- Push ------------------------------------------------------------

echo ">> Pushing to Artifact Registry"
docker push "$TAG"
docker push "$LATEST"

# --- Deploy ----------------------------------------------------------

# Image-only roll. Runtime env vars stay terraform-managed.
echo ">> Deploying to Cloud Run"
gcloud run deploy "$SERVICE" \
  --image="$TAG" \
  --region="$REGION" \
  --project="$PROJECT_ID"

URL="$(gcloud run services describe "$SERVICE" \
  --region="$REGION" \
  --project="$PROJECT_ID" \
  --format='value(status.url)')"

echo ""
echo "Deployed: $URL"
echo "Image:    $TAG"
