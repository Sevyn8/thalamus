# Deploy

Dev environment lives on Cloud Run v2 in `asia-south1`, project `ithina-retail-admin`. Service: `admin-frontend`. Artifact Registry: `admin-images`.

The current deploy bakes MSW mocks into the image (`NEXT_PUBLIC_USE_MOCKS=true` build-arg), so the demo URL is independent of any backend availability. Phase 4b wiring will flip the build-arg to `false` to point the image at Sanjeev's deployed backend.

## Separation of concerns

Two tools, two responsibilities — do not blur them:

- **Terraform** (`envs/dev/main.tf`) owns the Cloud Run service shape: scaling, region, IAM, and the `runtime_env` map (including `DEV_AUTH_PRIVATE_KEY_PEM` / `DEV_AUTH_PUBLIC_KEY_PEM`). The service's `lifecycle.ignore_changes` block covers the `image` field only — env vars are NOT ignored, so anything set out of band gets reverted on the next `terraform apply`.
- **`deploy-dev.sh`** rolls a new image revision. It does not touch env vars.

If you need to change `DEV_AUTH_*` values (or add new env vars), edit `envs/dev/main.tf` and `terraform apply`.

### Shared-infra coordination rule

The terraform repo is shared. **Always commit and push your terraform edit to the canonical infra repo BEFORE running `terraform apply`** — even if you applied it locally first.

The failure mode: you edit `envs/dev/main.tf` locally, `terraform apply` works, your service runs. Then a teammate pulls clean canonical state (which doesn't have your edit), runs their own `terraform apply`, and silently strips your env vars from the live service. The Cloud Run revision rolls without `DEV_AUTH_*_PEM`, `mint.ts` throws on the next persona switch, and your "working" deploy breaks without warning.

**Concrete incident (2026-05-04, 04:14 IST):** Sanjeev's `terraform apply` from a clean canonical clone stripped `DEV_AUTH_PRIVATE_KEY_PEM` / `DEV_AUTH_PUBLIC_KEY_PEM` from the deployed service. The persona switcher stopped working immediately — `lib/auth/mint.ts` threw on the JWT signing step because the env vars were unset and the standalone runtime has no `keys/dev-*.pem` files. Recovery required re-applying terraform from a tree that included the env-var entries.

Order of operations:

1. Edit `envs/dev/main.tf`.
2. Commit + push to the canonical infra repo.
3. Pull on whichever machine will apply (yours or a teammate's).
4. `terraform plan`, confirm scope, then `terraform apply`.

Never run `terraform apply` from an uncommitted local edit on a shared module.

### Targeted apply when teammate's pending changes are unrelated

If `terraform plan` shows pending backend / unrelated changes that aren't yours to ship, you can scope an apply to just the frontend service:

```bash
terraform apply -target='module.cloud_run_frontend.google_cloud_run_v2_service.frontend'
```

Caveat: `-target` is an escape hatch, not a routine workflow. It bypasses dependency resolution and can leave state inconsistent if used carelessly. Default is full apply after coordinating with whoever owns the pending changes; reach for `-target` only when frontend-only changes need to ship and the unrelated work is genuinely blocked on someone else's confirmation.

That said, this pattern saw two real uses in the 2026-05-03 → 05-04 window — both times because Sanjeev had pending backend module work in `terraform plan` that wasn't ready for apply. Documenting it here means the next time the situation comes up, the answer is in a shared place rather than re-derived.

## One-time setup

```bash
gcloud auth login
gcloud auth configure-docker asia-south1-docker.pkg.dev
gcloud config set project ithina-retail-admin
```

Local prerequisites: Docker daemon running, `keys/dev-private.pem` and `keys/dev-public.pem` present in repo root (the dev RS256 signing keys; gitignored, copy from your reference machine).

### First-time terraform apply

Before the first `./deploy-dev.sh`, the Cloud Run service needs the dev keys plumbed into its `runtime_env`. In `envs/dev/main.tf`, the `runtime_env` map should include the keys via `file()`:

```hcl
runtime_env = {
  NODE_ENV                 = "production"
  DEV_AUTH_PRIVATE_KEY_PEM = file("${path.root}/../../keys/dev-private.pem")
  DEV_AUTH_PUBLIC_KEY_PEM  = file("${path.root}/../../keys/dev-public.pem")
}
```

(Adjust the path if your terraform tree is laid out differently relative to the frontend repo's `keys/` directory.) Then `terraform apply` once before deploying the image. Re-apply only when key contents change.

## Deploy a new revision

```bash
./deploy-dev.sh
```

The script:

1. Validates `gcloud` is set to `ithina-retail-admin`, working tree is clean, dev keys are present (sanity check — terraform reads them at apply time).
2. Tags the image with the current git short SHA + `latest`.
3. Builds with `--build-arg NEXT_PUBLIC_USE_MOCKS=true`.
4. Pushes both tags to Artifact Registry.
5. Rolls the Cloud Run service to the new image (no env-var manipulation).
6. Prints the resulting `*.run.app` URL.

First deploy: ~6-8 minutes (Docker layer cache cold). Subsequent deploys: ~3 minutes.

## Roll back

List revisions:

```bash
gcloud run revisions list --service=admin-frontend --region=asia-south1
```

Send 100% of traffic to a previous revision:

```bash
gcloud run services update-traffic admin-frontend \
  --to-revisions=<revision-name>=100 \
  --region=asia-south1
```

## View logs

Last 50 entries:

```bash
gcloud run services logs read admin-frontend --region=asia-south1 --limit=50
```

Tail (use `gcloud beta` if not aliased):

```bash
gcloud run services logs tail admin-frontend --region=asia-south1
```

## Inspect current revision

```bash
gcloud run services describe admin-frontend \
  --region=asia-south1 \
  --format="value(spec.template.spec.containers[0].image)"
```

## Notes

- **Dev RS256 keys land in the Cloud Run revision spec via terraform's `runtime_env`** — env vars are not Secret-Manager-backed in Step 6.1. Acceptable as dev secrets, but they shouldn't be reused for production. A future step moves them to Secret Manager.
- **Phase 4b cleanup:** when the real backend takes over JWT minting, drop `DEV_AUTH_PRIVATE_KEY_PEM` / `DEV_AUTH_PUBLIC_KEY_PEM` from `envs/dev/main.tf` `runtime_env` and re-apply. The persona-switcher mint server route becomes inert.
- **Cold-start latency:** `min_instances=0` means the first request after idle takes ~3-5 seconds. Bump in Terraform if demo audiences find it rough.
- **Image architecture is amd64**, built natively on the Linux/WSL2 dev host. Apple Silicon developers must add `--platform linux/amd64` to the `docker build` step in `deploy-dev.sh`.
- **MSW gate** is `NEXT_PUBLIC_USE_MOCKS === "true" || NODE_ENV === "development"`. Dev (`pnpm dev`) gets MSW via `NODE_ENV`. Deploy gets MSW via the build-arg. Production builds without the build-arg get neither and call the real backend (Phase 4b).
