###############################################################################
# cloud-run-job-mirror-sync-consumer: the DIS Mirror Sync Cloud Run v2 JOB.
#
# A RUN-TO-COMPLETION job, not a service, despite the name. One execution = one
# sync pass = exit. It reads Customer Master's core.tenants / core.stores under a
# PLATFORM read context and upserts identity_mirror.tenants / .stores. This is the
# last piece of DIS that was still hand-seeded: without it, a tenant onboarded
# through CM gets no mirror row and DIS falls back to showing a UUID.
#
# Shape adapted from infra/modules/cloud-run-job-migrate-cm (the current job
# module, written the same day) with five deliberate divergences:
#
#   1. DEDICATED runtime SA, created here. migrate-cm reuses cm-backend-sa; that
#      was a pre-existing arrangement adopted by IMPORT, not a pattern to copy. A
#      job whose whole purpose is a least-privilege cross-schema read gets its own
#      identity.
#   2. NO command / args override. The image's CMD is
#      `python -m mirror_sync_consumer.pull.runner` and runner.main() parses
#      nothing - there is no argparse anywhere in the service - so there is no run
#      target to supply per execution. Contrast migrate-cm, which MUST override
#      the image CMD (that image starts uvicorn), and the square/clover connectors,
#      which take a per-execution `--args`.
#   3. TWO database connections, two roles, two secrets - see the read-role note
#      below. migrate-cm has one.
#   4. Its own image, built by terraform/docker/mirror-sync-consumer.Dockerfile.
#      migrate-cm shares the cm-backend image; this service has no image to share.
#   5. max_retries = 0 for a DIFFERENT reason than migrate-cm's. There, a retry is
#      dangerous (a half-applied migration re-run against a moved schema). Here a
#      retry would be SAFE - the upsert is idempotent by construction
#      (ON CONFLICT DO UPDATE ... WHERE IS DISTINCT FROM, so a no-change re-run is a
#      true no-op). It is still zero because the exit code is the operator's signal
#      and a silent retry muddies it.
#
# ==========================================================================
# WHY THE CM READ CONNECTS AS dis_mirror_reader, NOT user_admin_backend.
# ==========================================================================
# CM_DB_URL comes from the `dis-mirror-reader-database-url` secret, which connects
# as dis_mirror_reader: USAGE on schema core plus SELECT on exactly core.tenants and
# core.stores, and nothing else (infra/db-setup/sql/02_mirror_reader_grant.sql;
# verified live 2026-07-30 from a user_admin_backend session, the grantor reporting
# its own grants).
#
# DO NOT "SIMPLIFY" THIS TO cm-database-url. That secret already exists, it is right
# there, and it would work - which is exactly what makes it the easy mistake. It
# connects as user_admin_backend, which OWNS schema core and holds full DML. Handing
# a read-only mirror job write access to the identity system of record is the wrong
# posture, and nothing in the job would ever tell you it happened.
#
# The write half is unremarkable by comparison: POSTGRES_URL connects as
# ithina_dis_user (NOSUPERUSER NOBYPASSRLS), which 0001_bootstrap.py granted full
# DML on identity_mirror. Verified live via has_table_privilege from an
# ithina_dis_user session.
# ==========================================================================
#
# NOT granted here, by design:
#   - secretAccessor on cm-database-url. The job never needs it; see above.
#   - roles/cloudsql.client: the job reaches Cloud SQL over the private IP at the
#     TCP layer through the VPC connector, not via the Auth Proxy.
#   - No invoker binding. A job has no IAM policy in this project; executions are
#     operator-run via `gcloud run jobs execute` under the caller's own credentials.
#     No scheduler fires THIS job. That was once true project-wide and stopped being
#     true when the Synapse orchestrator got a Cloud Scheduler job — so
#     the deferral now applies to mirror-sync specifically rather than to the
#     project. It is still deliberate here: what cadence an identity mirror should
#     sync at is an open question, and Synapse's answer does not transfer (that is a
#     WORKER doing analysis inline; this would be a sync with its own freshness
#     requirement).
#   - Artifact Registry reader: image pulls use the Cloud Run service agent
#     (service-<num>@serverless-robot-prod...), not the runtime identity.
###############################################################################

# Dedicated runtime identity for the job (divergence 1).
resource "google_service_account" "mirror_sync_consumer" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "DIS Mirror Sync (mirror-sync-consumer) Cloud Run job runtime SA"
}

# The two DSN secrets, created out of band. The data sources resolve the ids for the
# grants and env refs below, and fail the plan fast if a secret is missing.
data "google_secret_manager_secret" "cm_read_url" {
  project   = var.project_id
  secret_id = var.secret_cm_read_url
}

data "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = var.secret_database_url
}

# Least-privilege: secretAccessor on exactly these two secrets. Not a project-wide
# grant, and deliberately NOT cm-database-url.
resource "google_secret_manager_secret_iam_member" "cm_read_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.cm_read_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.mirror_sync_consumer.email}"
}

resource "google_secret_manager_secret_iam_member" "database_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.mirror_sync_consumer.email}"
}

resource "google_cloud_run_v2_job" "mirror_sync_consumer" {
  # Staging: allow teardown. Terraform-side guard, not an API field; the provider
  # defaults it to true, so it is declared to keep config and state in agreement.
  deletion_protection = false

  project  = var.project_id
  name     = var.job_name
  location = var.region

  # Declared because both are Optional and NOT Computed in provider 6.50.0, the same
  # mechanism as the service-level scaling drift closed in 2a: an undeclared value
  # diffs on every plan forever. This job is terraform-CREATED rather than imported,
  # so these are what terraform will write, not a record of gcloud.
  #
  # There is deliberately NO service-level `scaling` block: google_cloud_run_v2_job
  # has none (its only top-level blocks are binary_authorization, template and
  # timeouts). That is a job/service difference, not an omission.
  client         = var.client
  client_version = var.client_version

  template {
    # One task per execution. The sync is a single pass over all tenants; nothing
    # about it parallelises, and two concurrent passes would race on the same
    # identity_mirror rows. parallelism is left unset (Optional+Computed).
    task_count = var.task_count

    template {
      service_account = google_service_account.mirror_sync_consumer.email

      # ZERO retries (divergence 5): the upsert is idempotent so a retry would be
      # harmless, but the exit code is how the operator judges the run and a silent
      # retry muddies the signal.
      max_retries = var.max_retries
      timeout     = var.task_timeout

      execution_environment = var.execution_environment

      # Egress to the private Cloud SQL IP via the Thalamus connector.
      # PRIVATE_RANGES_ONLY keeps public egress (Secret Manager) off the connector.
      # BOTH connections ride this: post-consolidation the CM read and the DIS write
      # are the same instance, same database, different roles and schemas.
      vpc_access {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image = var.image

        # NO command and NO args (divergence 2). The image CMD is the entrypoint and
        # runner.main() takes no arguments.

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        # STALE PRE-CONSOLIDATION DEFAULT, set explicitly. config.py's own default is
        # `ithina_platform_db` - the separate CM database that existed when this
        # service was written and which NO LONGER EXISTS. Inherited, the run exits 3
        # with "CM read connection is on 'thalamus', expected the Customer Master
        # database 'ithina_platform_db'": loud, but it names a database nobody has
        # heard of, which is the confusing part. The read target is now a SCHEMA
        # (core) inside the shared `thalamus` database.
        env {
          name  = "CM_DB_NAME"
          value = var.db_name
        }

        # STALE PRE-CONSOLIDATION DEFAULT, set explicitly. dis-rls's own default is
        # `ithina_dis_db` - likewise gone. Inherited, the write guard refuses
        # `thalamus` and the run exits 5 before any upsert is attempted. Same
        # parameterised guard the DIS services already set.
        env {
          name  = "DIS_EXPECTED_DATABASE"
          value = var.dis_expected_database
        }

        # The CM read connection (VALUE by reference only, never inline). Connects as
        # dis_mirror_reader - see the read-role block at the top of this file before
        # changing which secret this is.
        env {
          name = "CM_DB_URL"
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.cm_read_url.secret_id
              version = "latest"
            }
          }
        }

        # The DIS write connection. Connects as ithina_dis_user; dis-rls asserts the
        # role is NOSUPERUSER NOBYPASSRLS on first use.
        env {
          name = "POSTGRES_URL"
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

  depends_on = [
    google_secret_manager_secret_iam_member.cm_read_url,
    google_secret_manager_secret_iam_member.database_url,
  ]
}
