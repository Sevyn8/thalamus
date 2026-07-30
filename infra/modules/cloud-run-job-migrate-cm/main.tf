###############################################################################
# cloud-run-job-migrate-cm: the CM Alembic migration Cloud Run v2 JOB on the
# Thalamus data plane.
#
# THIS MODULE DESCRIBES A JOB THAT ALREADY EXISTS. It was written to match the
# LIVE configuration field-for-field and adopted by `terraform import`, not by
# creating anything. Every value below was read from the Cloud Run v2 REST API.
# The acceptance test for this module is `terraform plan` reporting no changes.
#
# ==========================================================================
# THE COMMAND OVERRIDE IS THE WHOLE POINT OF THIS JOB.
# ==========================================================================
# This job runs the SAME IMAGE as the cm-backend SERVICE (var.cm_image, shared -
# see D6 below). That image's CMD starts an API server:
#
#   CMD ["/bin/sh","-c","exec uvicorn admin_backend.main:app --host 0.0.0.0 \
#        --port ${PORT:-8080} --no-server-header"]      # cm-backend/Dockerfile:80
#
# The job OVERRIDES it with `command = ["alembic"]` / `args = ["upgrade","head"]`,
# so it does not go through the shell wrapper at all. cm-backend's own Dockerfile
# anticipates exactly this at line 77: "Cloud Run / GKE Job overrides CMD with
# `alembic upgrade head` for schema bring-up; the app itself never runs migrations
# on boot."
#
# DO NOT REMOVE OR "SIMPLIFY" command/args. Without them this job starts a web
# server that listens forever and migrates nothing. That failure presents as a
# HUNG JOB, not as a wrong command - the execution just never completes - so it is
# expensive to diagnose and easy to misread as a database or network problem.
# ==========================================================================
#
# Named `cloud-run-job-migrate-cm`, not `cloud-run-service-...`. The two existing
# job modules (cloud-run-service-{square,clover}-connector) are misnamed - both
# contain google_cloud_run_v2_job - and that misnaming is deliberately NOT
# propagated here. A job has no traffic, no ingress, no invoker binding, and no
# service-level scaling block at all. On the ledger.
#
# Shape adapted from infra/modules/cloud-run-service-square-connector (the proven
# job module) with these deliberate divergences:
#   1. command AND args ARE set. The square/clover connectors deliberately set
#      neither, because their run target arrives per execution via
#      `gcloud run jobs execute --args=...`; baking args there would pin a tenant
#      into a multi-tenant connector. This job is the opposite: one fixed
#      invocation, always the same, so it belongs in config.
#   2. No service account is created. The job runs as cm-backend-sa, which the
#      cloud-run-service-cm module owns; the email is passed in so there is one
#      source of truth and Terraform orders the SA before the job.
#   3. The image is SHARED with the cm-backend service (D6): both consume
#      var.cm_image. A second pin would let the migration run a different build
#      than the service it migrates for, which is the drift this avoids.
#   4. `client` / `client_version` are declared. The job was created by gcloud, and
#      both attributes are Optional and NOT Computed in provider 6.50.0, so an
#      undeclared value is a permanent diff. Same mechanism as the service-level
#      scaling drift closed in 2a; declared before it bites.
#   5. `parallelism` is deliberately NOT declared. The live job reports none, and
#      the attribute is Optional+Computed, so declaring 1 (as the square module
#      does) would write a value the API does not currently carry.
#
# IMAGE PROVENANCE CAVEAT, true as of this commit: var.cm_image resolves from
# infra/envs/staging/terraform.tfvars, which is UNTRACKED (.gitignore:13). The
# tracked default in envs/staging/variables.tf still says cm-backend:v1 while live
# is v13. So between this commit and the next one, this job's image is correct
# only because of a file that is not in git, and a clean-slate apply would run
# migrations from the wrong build. The next commit moves the pin into version
# control and deletes the shadowing tfvars line, which is what makes this honest.
#
# NOT granted here, by design:
#   - No service account and no secret IAM. cm-backend-sa already holds
#     secretAccessor on cm-database-url, granted by cloud-run-service-cm. Adding a
#     second grant here would duplicate an existing binding; this slice does not
#     touch IAM.
#   - No invoker binding. A job has no IAM policy of its own in this project (the
#     live policy is empty). Executions are operator-run via
#     `gcloud run jobs execute` under the caller's own credentials.
#   - roles/cloudsql.client: the job reaches Cloud SQL over the private IP at the
#     TCP layer through the VPC connector, not via the Auth Proxy.
###############################################################################

# The DATABASE_URL secret (created out-of-band; also consumed by the cm-backend
# service). The data source resolves the secret id for the env ref below and fails
# the plan fast if the secret is missing.
data "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = var.secret_database_url
}

resource "google_cloud_run_v2_job" "migrate_cm" {
  # Staging: allow teardown. The live job reports no deletionProtection, while the
  # provider's own default is true - declared so the two agree. This is a
  # terraform-state guard, not an API field.
  deletion_protection = false

  project  = var.project_id
  name     = var.job_name
  location = var.region

  # Created by `gcloud run jobs ...`, so the API reports these. Optional and NOT
  # Computed in the provider, so leaving them out diffs on every plan forever.
  # Do not "clean these up" - they are a record of how the job was made.
  client         = var.client
  client_version = var.client_version

  template {
    # One task per execution. A schema migration is not parallelisable: two
    # concurrent `alembic upgrade head` runs race on the alembic_version row.
    # parallelism is deliberately left unset (see divergence 5).
    task_count = var.task_count

    template {
      # cm-backend's runtime SA, owned by cloud-run-service-cm. Passed in rather
      # than created or hardcoded, so the SA exists before the job and there is
      # one source of truth for its email.
      service_account = var.service_account_email

      # ZERO retries, deliberately. A failed migration must stay failed and
      # visible: a silent retry of a half-applied migration is worse than a red
      # execution, because the second attempt runs against a schema the first one
      # already moved.
      max_retries = var.max_retries
      timeout     = var.task_timeout

      # GEN2 execution environment, matching the live job.
      execution_environment = var.execution_environment

      # Egress to the private Cloud SQL IP via the Thalamus connector.
      # PRIVATE_RANGES_ONLY keeps public egress (Secret Manager) off the connector.
      #
      # Takes the FULLY-QUALIFIED connector path (module.network.vpc_connector_id),
      # not the short name gcloud stored. The import surfaced the two spellings as
      # a diff and it was reconciled toward the long form: it is what all three
      # Terraform-created resources already carry, and passing the module output is
      # what orders the connector before the job.
      vpc_access {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image = var.image

        # THE OVERRIDE. See the block at the top of this file before touching
        # either line: the image's CMD starts uvicorn, and dropping these makes
        # the job hang serving HTTP instead of migrating.
        command = ["alembic"]
        args    = ["upgrade", "head"]

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        # Which Postgres schema Alembic targets. Parameterised per environment by
        # CM's own design (its DB_SCHEMA setting); `core` on staging.
        env {
          name  = "DB_SCHEMA"
          value = var.db_schema
        }

        # Secret env var (VALUE by reference only, never inline). Same secret the
        # cm-backend service consumes, so the migration and the app agree on the
        # target database by construction.
        env {
          name = "DATABASE_URL"
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
}
