# Deploying cm-frontend

Verified against the estate on 2026-08-15. Every command below was run and its output read.
Where something was not run, this file says so rather than guessing.

## What replaced the previous contents of this file

The previous version of this document described a project (`ithina-retail-admin`), a service
(`admin-frontend`), a Terraform tree (`envs/dev/main.tf`), a `lifecycle.ignore_changes` block on
the image field, and a `DEV_AUTH_*_PEM` stub-signing mechanism in `lib/auth/mint.ts`. None of
those exist. It also stated that `deploy-dev.sh` rolled the image while Terraform ignored it,
which is the opposite of how this service is deployed now. Both `deploy-dev.sh` and
`deploy-dev.ithina-dis-cm.sh` named dead projects and were deleted rather than repaired, matching
the precedent set for the cm-backend pair in commit `7988412`.

## Where it runs

Project `sevyn8-thalamus-staging`, region `asia-south1`, Cloud Run service `cm-frontend`.
Artifact Registry repository `thalamus-images`. Confirmed by listing the services:

```bash
gcloud run services list --region=asia-south1 --project=sevyn8-thalamus-staging \
  --format="value(metadata.name)"
```

## Terraform owns the image. This is the fact everything else follows from.

`infra/envs/staging/main.tf` passes `image = var.cm_frontend_image` into the module, and
`infra/modules/cloud-run-service-cm-frontend/main.tf` sets `image = var.image` on the service with
**no `lifecycle.ignore_changes` block**. So a `gcloud run deploy` would be reverted by the next
`terraform apply`. The image tag is changed by editing Terraform, not by deploying.

Note that `infra/envs/staging/variables.tf` currently describes `cm_frontend_image` as
"cm-frontend is deployed by gcloud". That description is wrong and is tracked separately; the
module is the authority.

## There is no cloudbuild for cm-frontend. The image is built by hand.

Six of the thirteen images in this estate have a cloudbuild file. cm-frontend is one of the seven
that do not, so nothing automates the build step: no CI exists in this repository at all.

## The sequence

Run end to end on 2026-08-15, producing `cm-frontend:v43`, which is the tag serving now.

1. **Build and push** to
   `asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/cm-frontend:<tag>`.
   The exact `docker build` invocation used is **not recorded here**, because it was not captured
   at the time and this file does not print commands it did not see run. What is known: the image
   path above is the one the service pulls, tags are explicit `vN` with no floating `latest`, and
   the Dockerfile emits a standalone Next build.

2. **Integrity gate.** Confirm the tag you just pushed resolves to a digest before wiring
   Terraform to it:

   ```bash
   gcloud artifacts docker images describe \
     asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/cm-frontend:v43 \
     --format="value(image_summary.digest)"
   ```

   Prints a `sha256:` digest. A tag that does not resolve fails here rather than at apply time,
   when the failure is a Cloud Run revision that cannot pull.

3. **Bump the pin.** Edit `cm_frontend_image` in `infra/envs/staging/variables.tf` to the new tag.

4. **Commit the edit before applying.** Terraform state is shared; an apply from an uncommitted
   local edit is how one person's change gets reverted by the next person's apply.

5. **Plan, then apply**, from `infra/envs/staging`:

   ```bash
   terraform plan
   terraform apply
   ```

   Expect an unrelated in-place change on `module.axon_sender_service` in every plan: its
   `scaling` block diffs `0 -> null` permanently. That drift is known and is not yours.

6. **Verify the SERVING IMAGE, not the revision name.** A new revision name only proves that
   something rolled:

   ```bash
   gcloud run services describe cm-frontend --region=asia-south1 \
     --project=sevyn8-thalamus-staging \
     --format="value(spec.template.spec.containers[0].image)"
   ```

   This printed
   `asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/cm-frontend:v43`
   when checked on 2026-08-15, against serving revision `cm-frontend-00052-ncf`.

## Rollback

**Unknown.** No rollback has been performed on this service in this estate, so there is nothing
here to describe from observation. Writing the general Cloud Run traffic-split command from memory
is exactly what made the previous version of this file dangerous. Establish it once, in a real
rollback, then record it here.

## Local checks before building

```bash
pnpm build
pnpm lint
```

`pnpm build` runs the four assertion scripts after `next build` and is the whole gate: this
package has no test runner. `pnpm lint` fails on warnings as well as errors, and treats an
eslint-disable directive that no longer suppresses anything as an error, so a stale suppression
breaks the build rather than accumulating quietly. Two problems remain from before that
tightening, an unescaped entity and an unused parameter, and both are tracked to ship with the
next cm-frontend image; until they do, lint still exits 1 on those two and only those two.
