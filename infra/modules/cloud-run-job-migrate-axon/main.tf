# =============================================================================
# migrate-axon - the way Axon's alembic chain reaches a database
# =============================================================================
#
# WHY THIS EXISTS AT ALL, ON THE FIRST SLICE OF THE MODULE. Because the alternative is a
# standing HIGH finding, already true of DIS: that chain reaches staging only by a hand-run
# alembic over the Cloud SQL proxy, and how its migrations were applied is recorded nowhere.
# migrate-synapse was written to stop that being true of a second plane. Shipping Axon without
# one would make it true of a third, to save copying a file.
#
# A hand-run chain is not merely undocumented. It runs from somebody's laptop, as whatever role
# their proxy session holds, against whatever database that session points at, with no record
# of which revision was applied when. Every one of those is a variable this job removes.
#
# SHAPE MIRRORS cloud-run-job-migrate-synapse, which mirrors migrate-cm:
#
#   1. THE SAME IMAGE AS THE WORKLOAD, with the entrypoint overridden. migrate-cm shares its
#      image with cm-backend for a stated reason (D6): a separately pinned migration image can
#      run a different build than the code it migrates for. Axon has no image of its own, so
#      the workload here is synapse-ui-server, whose Dockerfile COPYs the whole axon/ directory
#      including this chain and the DDL it applies.
#   2. command AND args ARE BOTH SET. Without the override this job starts uvicorn and hangs
#      until its timeout, which is migrate-cm's recorded failure mode rather than a guess.
#   3. VPC connector, PRIVATE_RANGES_ONLY. Cloud SQL is private IP only (ipv4Enabled=false,
#      10.55.0.3), reached at the TCP layer exactly as every other workload here reaches it.
#   4. A DEDICATED SERVICE ACCOUNT. The BFF's runtime identity holds secretAccessor on
#      axon_sender's DSN, which is INSERT on one table. An admin DSN is a strictly higher
#      privilege and the request-serving identity must not hold it: a service that answers HTTP
#      should not be able to ALTER the schema it writes to.
#
# `alembic -c /axon/alembic.ini`, an ABSOLUTE config path. Cloud Run v2 exposes no working
# directory and the image's WORKDIR is /app while the chain lives at /axon. Safe because
# nothing in the chain is CWD-sensitive, and all three reasons were checked rather than
# assumed: alembic.ini sets `script_location = %(here)s/alembic` (resolved against the ini's
# own directory), env.py imports no axon package, and 0001 locates its DDL through
# `Path(__file__).resolve().parents[2]`.
#
# THE VERSION TABLE IS `axon_alembic_version` IN THE DEFAULT SCHEMA - env.py, and explicitly
# NOT version_table_schema="axon". Three chains now share this database and each would read
# another's head as its own if they shared a table. Alembic also creates the version table
# BEFORE running the migration that would create the schema, so the schema-qualified form fails
# on a fresh database.
#
# THE ROLE axon_sender MUST EXIST BEFORE THIS RUNS. 0001 grants USAGE on the schema to it, so a
# missing role fails the migration rather than the later grant file. Migration 0006 in the
# Synapse chain recorded that ordering hazard; this is the same one, avoided by sequence.
#
# THE ADMIN PASSWORD MUST BE URL-SAFE OR PERCENT-ENCODED. An unencoded '@' parses as the host
# separator, so the DSN silently points somewhere else instead of failing - learned empirically
# 2026-08-06. This secret is created by hand and carries no Terraform-generated guarantee.

data "google_secret_manager_secret" "admin_url" {
  project   = var.project_id
  secret_id = var.secret_admin_url
}

# The migration identity. Separate from the BFF's on purpose - see the header.
resource "google_service_account" "migrate_axon" {
  project      = var.project_id
  account_id   = "migrate-axon-sa"
  display_name = "migrate-axon - runs Axon's alembic chain"
  description  = "Holds secretAccessor on the axon ADMIN DSN and nothing else. Deliberately NOT the BFF's identity: a service that answers HTTP must never hold DDL rights on the ledger it writes."
}

resource "google_secret_manager_secret_iam_member" "admin_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.admin_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migrate_axon.email}"
}

resource "google_cloud_run_v2_job" "migrate_axon" {
  deletion_protection = false

  project  = var.project_id
  name     = var.job_name
  location = var.region

  client         = var.client
  client_version = var.client_version

  template {
    template {
      service_account = google_service_account.migrate_axon.email
      max_retries     = var.max_retries
      timeout         = var.task_timeout

      vpc_access {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image = var.image

        # DO NOT REMOVE OR "SIMPLIFY". Without the override this starts uvicorn and hangs.
        command = ["alembic"]
        args    = ["-c", "/axon/alembic.ini", "upgrade", "head"]

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        # AXON_ADMIN_URL, not SYNAPSE_ADMIN_URL and not POSTGRES_ADMIN_URL. env.py refuses to
        # fall back to either, because one chain's URL silently driving another is exactly the
        # failure a shared database invites. Three chains, three variables.
        env {
          name = "AXON_ADMIN_URL"
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.admin_url.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.admin_url]
}
