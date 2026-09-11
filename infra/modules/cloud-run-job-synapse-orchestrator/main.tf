###############################################################################
# Synapse orchestrator: a Cloud Run JOB and the Cloud Scheduler job that fires it.
#
# ONE EXECUTION IS ONE SWEEP. `python -m synapse.orchestrator` enumerates every active row in
# synapse.provision, works out each tenant's due slot IN THAT TENANT'S OWN TIMEZONE, resolves
# and evaluates the declaration, appends actions to synapse.actions, and records a row in
# synapse.run. It exits when it is done.
#
# SHADOW ONLY. Nothing is delivered anywhere: no channel, no notification, no escalation. The
# orchestrator REFUSES any rung above SHADOW rather than approximating it, so enabling delivery
# is the deletion of an explicit refusal rather than a configuration change here.
#
# ==========================================================================
# TWO IDENTITIES, AND THE SPLIT IS THE POINT
# ==========================================================================
#   RUNTIME SA (google_service_account.orchestrator)
#     What the container runs as. Holds secretAccessor on exactly the two DSN secrets and
#     nothing else. It cannot invoke itself.
#
#   SCHEDULER SA (google_service_account.scheduler)
#     What Cloud Scheduler authenticates as when it calls the Run Admin API. Holds
#     roles/run.invoker ON THIS JOB RESOURCE ONLY — not project-wide, so it can start this one
#     job and nothing else in the project.
#
# A single SA would work and would mean the thing that runs the sweep can also trigger it,
# which is a strictly larger blast radius for no benefit.
#
# NOT granted, by design:
#   - roles/cloudsql.client. The job reaches Cloud SQL over the private IP through the VPC
#     connector at the TCP layer, not via the Auth Proxy. Same as mirror-sync-consumer.
#   - Any grant on synapse.provision. Provisioning is an operator act performed by hand as the
#     schema owner (infra/db-setup/sql/provision_analysis.sql); migration 0003 gives the
#     runtime roles nothing on that table, so a bug in the orchestrator cannot enable a
#     customer.
#   - Artifact Registry reader. Image pulls use the Cloud Run service agent, not the runtime
#     identity.
# ==========================================================================

resource "google_service_account" "orchestrator" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "Synapse orchestrator Cloud Run job runtime SA"
}

resource "google_service_account" "scheduler" {
  project      = var.project_id
  account_id   = var.scheduler_service_account_id
  display_name = "Synapse orchestrator Cloud Scheduler invoker SA"
}

# The two DSN secrets, created out of band. The data sources resolve the ids for the grants and
# env refs below, and fail the PLAN fast if a secret is missing — which is the right time to
# find out, rather than at 03:00 on a container that cannot start.
#
# BOTH ALREADY EXIST: synapse-reader-database-url and synapse-writer-database-url version 1.
# Terraform only ever READS DSN secrets in this project; there is no resource creating a
# *-database-url anywhere in infra/.
data "google_secret_manager_secret" "reader_url" {
  project   = var.project_id
  secret_id = var.secret_reader_url
}

data "google_secret_manager_secret" "writer_url" {
  project   = var.project_id
  secret_id = var.secret_writer_url
}

resource "google_secret_manager_secret_iam_member" "reader_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.reader_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.orchestrator.email}"
}

resource "google_secret_manager_secret_iam_member" "writer_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.writer_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.orchestrator.email}"
}


resource "google_cloud_run_v2_job" "orchestrator" {
  # Staging: allow teardown. Terraform-side guard, not an API field; declared so config and
  # state agree, matching the mirror-sync job.
  deletion_protection = false

  project  = var.project_id
  name     = var.job_name
  location = var.region

  # Declared for the same reason as mirror-sync's: both are Optional and NOT Computed, so an
  # undeclared value diffs on every plan forever.
  client         = var.client
  client_version = var.client_version

  template {
    # One task. The sweep is a single pass over all provisioned pairs. Two concurrent passes
    # would both be SAFE — the slot key admits one run row per slot and the actions index
    # suppresses duplicates — but they would race to write the same run row's counts, and there
    # is no work to parallelise across.
    task_count = var.task_count

    template {
      service_account = google_service_account.orchestrator.email

      # ONE RETRY, and this is a deliberate divergence from mirror-sync's zero.
      #
      # The orchestrator has a TAKEOVER path: a run that crashes mid-sweep leaves its row with
      # outcome NULL, and the next attempt adopts and completes it. With max_retries = 0 that
      # path could only ever fire on the NEXT DAY'S dispatch — twenty-four hours later — which
      # is building the mechanism and then setting the knob that stops it running while it
      # matters. One retry lets a crashed sweep finish minutes later.
      #
      # It is a clean no-op for the other case: a run that recorded a terminal outcome is
      # SKIPPED by claim(), so a retry after a genuine analytic failure re-attempts nothing.
      # The skip carries the prior outcome through, so the retry still exits non-zero and the
      # execution stays RED — without that, retrying would convert a real failure into a green
      # execution at exactly the layer an alert watches.
      max_retries = var.max_retries
      timeout     = var.task_timeout

      execution_environment = var.execution_environment

      # Egress to the private Cloud SQL IP via the Thalamus connector. PRIVATE_RANGES_ONLY
      # keeps public egress (Secret Manager) off the connector.
      vpc_access {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image = var.image

        # NO command and NO args. The image's ENTRYPOINT is `python -m synapse.orchestrator`
        # and a scheduled execution wants the full sweep, which is what no arguments means.
        #
        # THIS IS WHAT KEEPS THE JOB HAND-RUNNABLE. `gcloud run jobs execute <job>
        # --args=--dry-run` overrides ARGS and leaves the ENTRYPOINT intact, so an operator
        # runs the SAME code path the scheduler does with different arguments. Scheduling is an
        # addition, not a replacement.

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        # dis-rls refuses any database except its expected one, defaulting to the
        # pre-consolidation `ithina_dis_db` which no longer exists. Inherited, every query
        # fails with RlsContextError before touching a row — and RlsContextError is not a
        # SynapseError, so it escapes the handler as an uncaught traceback rather than the
        # tidy exit 2. Set explicitly, like every other service here.
        env {
          name  = "DIS_EXPECTED_DATABASE"
          value = var.dis_expected_database
        }

        # The READ connection: synapse_reader. SELECT on two canonical tables, synapse.actions,
        # synapse.provision and synapse.run. No write anywhere.
        env {
          name = "SYNAPSE_READER_URL"
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.reader_url.secret_id
              version = "latest"
            }
          }
        }

        # The WRITE connection: synapse_writer. INSERT on synapse.actions, the run state
        # machine on synapse.run, and NOTHING on canonical or on synapse.provision.
        #
        # TWO DSNs, NOT ONE, and passing the same value for both is a real error rather than a
        # shortcut: the reader would fail on the first append, the writer on the first
        # canonical read. Both fail loudly because the split is grants rather than discipline.
        env {
          name = "SYNAPSE_WRITER_URL"
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.writer_url.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }
}


# The scheduler may start THIS JOB and nothing else. Scoped to the job resource rather than the
# project, so the invoker cannot reach any other Cloud Run workload.
resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_job.orchestrator.location
  name     = google_cloud_run_v2_job.orchestrator.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}


###############################################################################
# THE SCHEDULE
#
# ==========================================================================
# THE CRON IS UTC AND THE SLOT IS TENANT-LOCAL. THAT GAP IS THE WHOLE DESIGN.
# ==========================================================================
# `30 21 * * *` UTC = 03:00 the following day in Asia/Kolkata (UTC+05:30), which is where the
# only provisioned tenant reports. That window is chosen for two reasons:
#
#   - AFTER overnight ingestion of the previous day, so positions are dated against fresh
#     sales rather than yesterday's picture.
#   - WELL CLEAR OF LOCAL MIDNIGHT. The slot is floored in the tenant's own zone, and
#     synapse.core.slot names the residual: a dispatch within minutes of local midnight can
#     have its RETRY floor to a different date, producing two runs for what was one intent.
#     03:00 is three hours of margin either side.
#
# time_zone is UTC DELIBERATELY, not Asia/Kolkata. Setting the scheduler's zone to the tenant's
# would put a per-customer operational fact into terraform — the same thing the provision table
# exists to keep out of the release cycle. UTC is also DST-free, so the fired instant never
# moves under a tenant whose zone observes it.
#
# ==========================================================================
# THE RULE, WHICH IS A QUERY RATHER THAN A JUDGEMENT
# ==========================================================================
# EVERY PROVISIONED TENANT'S LOCAL FIRE TIME MUST FALL BETWEEN 02:00 AND 05:00. One cron fires
# at one instant, so each tenant experiences it at a different local hour; as tenants spread
# across zones, some tenant's local fire time eventually lands near midnight and the residual
# above becomes real for them.
#
# Check it before provisioning a tenant in a NEW zone, and re-check it after. Substitute the
# candidate cron instant:
#
#   BEGIN;
#     SELECT set_config('app.user_type','PLATFORM',true);
#     SELECT tenant_id, timezone,
#            (TIMESTAMPTZ '2026-08-06 21:30:00+00') AT TIME ZONE timezone AS local_fire_time
#       FROM synapse.provision WHERE disabled_at IS NULL;
#   ROLLBACK;
#
# (The PLATFORM set_config is not optional: synapse.provision is FORCE RLS and a bare SELECT
# returns zero rows for every role including the owner. See infra/db-setup/README.md.)
#
# WHEN NO SINGLE INSTANT SATISFIES EVERY TENANT, this model is finished and that query is what
# says so. The successor is per-tenant scheduling — an hourly dispatch plus a declared local
# run hour on the provision row — which is a slice of its own and deliberately not guessed at
# here.
#
# ==========================================================================
# WHY THE SCHEDULER DOES NOT RETRY
# ==========================================================================
# retry_count = 0. The job's own max_retries = 1 already covers the case a retry can help (a
# crashed sweep, adopted via takeover). A scheduler retry is a DIFFERENT thing — it launches a
# second EXECUTION — and the slot key already makes that harmless rather than useful: the
# second execution finds every slot terminal and skips it. Two mechanisms retrying the same
# work in different ways is how a retry storm starts; one is enough, and it is the one closer
# to the failure.
###############################################################################

resource "google_cloud_scheduler_job" "orchestrator_daily" {
  project     = var.project_id
  region      = var.region
  name        = var.scheduler_job_name
  description = "Daily Synapse shadow-mode sweep. 03:00 Asia/Kolkata; see module main.tf."

  schedule  = var.schedule
  time_zone = var.schedule_time_zone

  # A sweep over a handful of tenants finishes in seconds; this bounds the API CALL, not the
  # job, which has its own task_timeout.
  attempt_deadline = var.attempt_deadline

  retry_config {
    retry_count = var.scheduler_retry_count
  }

  http_target {
    http_method = "POST"
    # The Run Admin API v2 :run endpoint. A Cloud Run JOB is started through this API rather
    # than by an HTTP request to the container — which is why the container receives no headers
    # and X-CloudScheduler-ScheduleTime (an HTTP-TARGET header) never reaches it. That is the
    # reason the slot is floored in-process from the container's own clock.
    uri = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.orchestrator.name}:run"

    # oauth_token, NOT oidc_token: the target is a Google API, which authenticates with an
    # OAuth access token. oidc_token is for calling your own services.
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_invoker]
}
