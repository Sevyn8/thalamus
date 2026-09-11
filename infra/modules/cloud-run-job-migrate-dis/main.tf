# =============================================================================
# migrate-dis — the way DIS's alembic chain reaches a database
# =============================================================================
#
# This job is the ONLY mechanism that applies DIS's alembic chain to a deployed
# database; nothing else in the repository holds POSTGRES_ADMIN_URL outside tests.
# A run against an already-at-head database is a deliberate no-op that still proves
# the mechanism: image, identity, secret, VPC path, target guard, version table.
# Same proving pattern migrate-synapse used. A first run that also applied DDL would conflate
# "the job works" with "the migration works", and a failure would not say which.
#
# It also means this job's value is entirely prospective: revision 0020 is the first one that
# will reach staging without somebody opening a proxy and running alembic from a laptop.
#
# SHAPE MIRRORS cloud-run-job-migrate-synapse, which mirrors cloud-run-job-migrate-cm, because
# that lineage is the proven pattern here:
#
#   1. command AND args ARE BOTH SET, even though this image's ENTRYPOINT already runs the
#      upgrade. Both ancestors override a CMD that would otherwise start something long-lived
#      (uvicorn; Synapse's daily sweep) where the failure mode is a HUNG JOB rather than a
#      visible wrong command. Nothing in this image starts a server, so the override is
#      belt-and-braces — but it is also the only place the ini path is stated in terraform,
#      which is where an operator looks.
#   2. VPC connector, PRIVATE_RANGES_ONLY. Cloud SQL is private IP only (ipv4Enabled=false,
#      10.55.0.3), reached at the TCP layer exactly as the workloads reach it.
#   3. max_retries = 0. A migration that fails must be looked at, not retried.
#   4. The secret is read through a `data` source so a missing secret fails the PLAN rather
#      than the execution.
#
# WHAT IS DIFFERENT FROM migrate-synapse — all of it, because "clone it" hides these:
#
#   - A DEDICATED IMAGE rather than the workload's. Synapse's chain lives inside the synapse
#     package, so the orchestrator image already carried it. DIS's chain lives at the WORKSPACE
#     ROOT and alembic is declared only by the root `ithina-dis` project — measured: zero
#     alembic occurrences in the resolved closure of csv-ingest-worker, streaming-consumer,
#     mirror-sync-consumer or dis-ui-server. See terraform/docker/migrate-dis.Dockerfile for
#     the full argument, including what this forfeits (migrate-cm's D6 same-build property,
#     which DIS cannot have for four workloads on one schema anyway).
#   - POSTGRES_ADMIN_URL, not SYNAPSE_ADMIN_URL. env.py:40. The two chains deliberately refuse
#     to read each other's variable.
#   - POSTGRES_DB, WHICH HAS NO ANALOGUE IN migrate-synapse AND IS LOAD-BEARING. See below.
#   - `-c /app/alembic.ini`, not /synapse/alembic.ini — this image's WORKDIR is /app.
#   - THE VERSION TABLE IS `alembic_version`, the alembic default: env.py sets no
#     `version_table`. Synapse's is `synapse_alembic_version` precisely so two chains sharing
#     one database do not read each other's head as their own. DIS holds the default name
#     because DIS was there first.
#
# ============================================================================================
# POSTGRES_DB IS NOT OPTIONAL AND ITS ABSENCE FAILS EVERY REVISION
# ============================================================================================
# EIGHTEEN of the nineteen revisions open with a target-safety guard:
#
#     _EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")
#     ...
#     raise RuntimeError("Refusing to run DIS migration: connected to '<current>' but
#                         expected DIS database '<expected>' (POSTGRES_DB).")
#
# (0019:79 and :114-118; the same block in 0001..0018 bar 0006.) The staging database is
# `thalamus`, NOT `ithina_dis_db` — so WITHOUT this variable every revision refuses, including
# the only one currently outstanding. The guard is doing its job; it is calibrated for the
# local devbox, where DIS is on 5433 and Customer Master on 5432, and it hard-blocks
# `ithina_platform_db` by name regardless of what this is set to.
#
# The hand-run set exactly this: infra/db-setup/README.md:116 records DIS running its
# migrations as `postgres` with `POSTGRES_DB=thalamus`. This job reproduces that environment
# rather than inventing one.
#
# ============================================================================================
# THE ROLE IS `postgres`, AND ITS OWN SOURCE IS WRONG IN TWO SEPARATE WAYS
# ============================================================================================
# infra/db-setup/README.md is the only record of how DIS's chain reached this database, and
# NEITHER of its two statements about that run can be taken at face value:
#
#   :32  (the PLAN)   "DIS Alembic (`ithina-retail-dis`, `POSTGRES_URL` -> the shared DB as
#                      `ithina_dis_user`)"
#   :47  (the STATUS) "DIS Alembic as `postgres` (8 schemas + 18 revisions)"
#
#   1. THE ROLE. The plan line says `ithina_dis_user`; the status line says `postgres`. The
#      status line describes what was ACTUALLY RUN, is corroborated at :116
#      (`POSTGRES_ADMIN_URL=postgres`), and is now CONFIRMED against the database: ownership is
#      uniform `postgres` across all eight DIS schemas, checked 2026-08-07. The plan line is
#      stale, not a second option. It must stay `postgres` — objects created by another role
#      would be owned differently from the tables they sit on.
#
#   2. THE REVISION COUNT. The status line says 18. The live stamp is 0019, so at least one
#      revision was hand-applied AFTER 2026-07-20 and nobody updated the file. That is the more
#      instructive half: the README is a point-in-time note that reads like a standing record,
#      and its number drifted the moment somebody ran alembic without editing it.
#
# BOTH ARE WHY THIS JOB EXISTS RATHER THAN A RUNBOOK PARAGRAPH. A mechanism that runs leaves a
# version table behind; a document describing a mechanism drifts silently and is believed
# anyway. The stamp is the truth, the README is a memory of it — check
# `SELECT version_num FROM alembic_version` before trusting any prose about this chain,
# including these comments.
#
# THE ADMIN PASSWORD MUST BE URL-SAFE OR PERCENT-ENCODED. An unencoded '@' parses as the host
# separator, so the DSN silently points somewhere else instead of failing — learned empirically
# on migrate-synapse, 2026-08-06. The postgres password is NOT Terraform-generated and carries
# no `override_special` guarantee, unlike the reader/writer DSNs (sql/03).

data "google_secret_manager_secret" "admin_url" {
  project   = var.project_id
  secret_id = var.secret_admin_url
}

# The migration identity. Separate from every workload's on purpose: an admin DSN is a
# strictly higher privilege than any DIS service needs, and granting a data-path service
# account access to it would leave that service holding DDL rights permanently.
resource "google_service_account" "migrate_dis" {
  project      = var.project_id
  account_id   = "migrate-dis-sa"
  display_name = "migrate-dis — runs DIS's alembic chain"
  description  = "Holds secretAccessor on the DIS ADMIN DSN and nothing else. Deliberately NOT csv-ingest-worker's, streaming-consumer's or dis-ui-server's identity: no data-path service should hold DDL rights."
}

resource "google_secret_manager_secret_iam_member" "admin_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.admin_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.migrate_dis.email}"
}

resource "google_cloud_run_v2_job" "migrate_dis" {
  deletion_protection = false

  project  = var.project_id
  name     = var.job_name
  location = var.region

  client         = var.client
  client_version = var.client_version

  template {
    template {
      service_account = google_service_account.migrate_dis.email
      max_retries     = var.max_retries
      timeout         = var.task_timeout

      vpc_access {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image = var.image

        # STATED HERE EVEN THOUGH THE IMAGE'S ENTRYPOINT MATCHES. Both ancestor modules carry
        # this override because their images would otherwise start a server; this one keeps it
        # so the ini path is visible in terraform and so a future base-image change cannot
        # silently alter what the job runs.
        command = ["alembic"]
        args    = ["-c", "/app/alembic.ini", "upgrade", "head"]

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        # The DSN. env.py:40 reads this, falls back to a repo-root .env that does not exist in
        # the image, and then RAISES rather than defaulting to anything (env.py:58) — so a
        # missing secret is a loud failure, not a run against the wrong database.
        env {
          name = "POSTGRES_ADMIN_URL"
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.admin_url.secret_id
              version = "latest"
            }
          }
        }

        # NOT A CONVENIENCE. Eighteen of nineteen revisions refuse to run unless this matches
        # the connected database — see the header. Plain env rather than a secret: it is a
        # database NAME, it is already in this repository in a dozen places, and putting it in
        # Secret Manager would hide the one value an operator most needs to read when the job
        # refuses.
        env {
          name  = "POSTGRES_DB"
          value = var.expected_database
        }
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.admin_url]
}
