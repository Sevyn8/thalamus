###############################################################################
# cloud-run-service-square-connector: the Thalamus Square connector on the
# Thalamus data plane.
#
# A Cloud Run JOB, not a Service. One execution is ONE trigger: the container
# runs python -m thalamus_square.real_transport, which mints the producer-owned
# ids, builds a ConnectorTrigger and runs a single Square catalog pull
# (extract -> CSV -> bronze -> ingress.ready), then exits. There is no loop, no
# server, no port and no health probe.
#
# Shape adapted from infra/modules/cloud-run-service-csv-ingest-worker, with:
#   1. google_cloud_run_v2_job, not _service. A Job has no scaling, traffic,
#      ingress, ports, startup_probe or cpu_idle: CPU is always allocated for
#      the life of the task, so the worker's cpu_idle=false / min=max=1 pins
#      have no analogue here. max_retries=0: a manually executed pull must fail
#      loudly, not silently re-run (the retry would be SAFE - same run_key ->
#      same connector_run_id -> the D58 dedup collapses it to duplicate_noop -
#      but a silent retry hides the first failure).
#   2. NO baked args. The run target (tenant/store/source/template/run-key) is
#      supplied per execution via `gcloud run jobs execute --args`; terraform
#      never names a tenant. A bare execute fails on argparse with exit 2,
#      deliberately. The image's ENTRYPOINT carries the module invocation, so
#      --args passes only the run target.
#   3. PUBLISHES but never subscribes: pubsub.publisher on the ingress.ready
#      topic, and NO subscription grant.
#   4. Square OAuth: reads the per-tenant token vault the BFF writes at
#      OAuth-complete time (see squareTokenVaultRefresher below), plus
#      secretAccessor on square-app-secret for the refresh call.
#   5. storage.objectAdmin on bronze: the connector is the PRODUCER of the
#      bronze object (the CSV worker reads one a producer wrote).
#
# NOT granted here, by design:
#   - roles/pubsub.viewer: csv-ingest-worker and streaming-consumer hold it at
#     project level for their startup _require_subscription preflight
#     (subscriptions.get, subscriber.py). The connector only PUBLISHES, and
#     PubsubPublisher does no topics.get preflight - it constructs the client
#     and publishes. Nothing here needs viewer.
#   - roles/cloudsql.client: connects over the private IP at the TCP layer
#     (POSTGRES_URL host = 10.55.0.3, sslmode=require) through the VPC
#     connector. No socket/proxy is used anywhere in the connector.
#   - Artifact Registry reader: image pulls use the Cloud Run service agent.
#   - secretmanager.secrets.create: withheld from squareTokenVaultRefresher.
#     GoogleSecretBackend.add_version falls back to create_secret on NotFound,
#     but that fallback is UNREACHABLE for this SA: the only caller is
#     VaultTokenStore.get_token, which reads the vault FIRST and raises
#     ConnectorAuthError ("the tenant has not connected Square") when the secret
#     is absent, so the write path is never reached without an existing secret.
#     Creating token secrets is the BFF's job (squareTokenVaultWriter).
#   - roles/secretmanager.secretAccessor at project level: too broad. The two
#     named secrets are resource-scoped grants; the per-tenant token vault gets
#     the narrow custom role instead.
#   - An IAM condition on squareTokenVaultRefresher. A name-prefix condition
#     (resource.name.startsWith(".../secrets/square-oauth-")) is the available
#     tightening, and it applies EQUALLY to the existing squareTokenVaultWriter
#     on dis-ui-server. Deliberately deferred so the two roles stay consistent:
#     conditioning one while its neighbour is unconditioned is worse than
#     conditioning neither. Tighten both together or neither.
###############################################################################

# Dedicated runtime identity for the connector job.
resource "google_service_account" "square_connector" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "Thalamus square-connector Cloud Run job runtime SA"
}

# Existing secrets (created out of band). Data sources resolve the ids for the
# IAM grants below and fail the plan fast if a secret is missing.
data "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = var.secret_database_url
}

data "google_secret_manager_secret" "square_app_secret" {
  project   = var.project_id
  secret_id = var.secret_square_app_secret
}

# Least-privilege runtime grants, resource-scoped where the resource supports it.
resource "google_secret_manager_secret_iam_member" "database_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.square_connector.email}"
}

# The Square client_secret, needed for the OAuth refresh-token grant.
resource "google_secret_manager_secret_iam_member" "square_app_secret" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.square_app_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.square_connector.email}"
}

# The per-tenant Square OAuth token vault: one secret per (tenant, source), named
# square-oauth-{tenant_uuid}-{slug}-{hash8} (thalamus_square_oauth/naming.py) and
# MINTED AT OAUTH-COMPLETE TIME by the BFF. The names therefore do not exist when
# this plan runs and cannot be resource-scoped, so this is a narrow project-scoped
# custom role rather than roles/secretmanager.secretAccessor at project level.
# Mirrors the squareTokenVaultWriter precedent on cloud-run-service-dis-ui-server.
#
# versions.add is REQUIRED, not optional: VaultTokenStore.get_token refreshes when
# the access token is within the skew of expiry and then PERSISTS the rotated set
# (vault.write -> add_secret_version). Without it, every execution past
# expires_at - 3 days fails with PermissionDenied AFTER a successful Square
# refresh, leaving the rotated token unpersisted - a silent ~27-day cliff.
# secrets.get is unexercised today (access_latest calls access_secret_version and
# catches NotFound) but mirrors the writer role and is what a cheap "is this
# source connected" check would use.
resource "google_project_iam_custom_role" "square_token_vault_refresher" {
  project     = var.project_id
  role_id     = "squareTokenVaultRefresher"
  title       = "Square token vault refresher (square-connector)"
  description = "Read + refresh-and-persist the per-tenant Square OAuth token secrets."
  permissions = [
    "secretmanager.secrets.get",
    "secretmanager.versions.access",
    "secretmanager.versions.add",
  ]
}

resource "google_project_iam_member" "square_token_vault_refresher" {
  project = var.project_id
  role    = google_project_iam_custom_role.square_token_vault_refresher.id
  member  = "serviceAccount:${google_service_account.square_connector.email}"
}

# The connector PRODUCES the bronze object (CSV serialized from the Square pull),
# so objectAdmin - not the streaming-consumer's read-only objectViewer.
resource "google_storage_bucket_iam_member" "bronze_object_admin" {
  bucket = var.bronze_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.square_connector.email}"
}

resource "google_pubsub_topic_iam_member" "ingress_publisher" {
  project = var.project_id
  topic   = var.ingress_topic_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.square_connector.email}"
}

locals {
  # Plain env. Names are the EXACT vars the connector's config resolves.
  # REQUIRED at boot: PUBSUB_PROJECT_ID, GCS_BUCKET_BRONZE (SdkConfig.from_env)
  # and SQUARE_CLIENT_ID / SQUARE_SECRETS_PROJECT_ID (SquareOAuthConfig.from_env,
  # reached only because real_transport injects no token_store). POSTGRES_URL and
  # SQUARE_APP_SECRET are secret env, below.
  #
  # STORAGE_EMULATOR_HOST and PUBSUB_EMULATOR_HOST are deliberately ABSENT: both
  # clients are emulator-or-ambient and would silently redirect off GCP if set.
  # SQUARE_API_VERSION and SQUARE_OAUTH_REFRESH_SKEW_SECONDS are left UNSET: the
  # in-code defaults (a pinned Square-Version, a 3-day skew) are the intent.
  # There is no RUN_HEALTH_SERVER/PORT: a Job serves nothing.
  plain_env = {
    DIS_EXPECTED_DATABASE = var.dis_expected_database # dis-rls guard (session.py:52); "thalamus" here, NOT the ithina_dis_db default
    PUBSUB_PROJECT_ID     = var.project_id            # sdk/config.py:43 required at boot
    GCS_BUCKET_BRONZE     = var.bronze_bucket_name    # sdk/config.py:46 required at boot (written)
    # INGRESS_READY_TOPIC is resolved at IMPORT time as a module constant
    # (csv_ingest_worker/config.py:57, default "ingress.ready") and the SDK pipeline
    # publishes to it directly. It MUST name the provisioned topic or the connector
    # publishes to a topic that does not exist.
    INGRESS_READY_TOPIC = var.ingress_ready_topic
    # The Square host: the API base AND the OAuth base AND the environment stamp.
    # SquareOAuthConfig derives environment = sandbox iff the host contains
    # "squareupsandbox" (config.py:90-91), and that string is stamped onto every
    # token set the connector rotates. NOT SQUARE_OAUTH_BASE_URL - that is the
    # BFF's variable name for the same host.
    SQUARE_API_BASE_URL       = var.square_api_base_url # config.py:53 + :90
    SQUARE_CLIENT_ID          = var.square_client_id    # config.py:79 required on the real path
    SQUARE_SECRETS_PROJECT_ID = var.project_id          # config.py:85 the token vault's project
  }
}

resource "google_cloud_run_v2_job" "square_connector" {
  # Staging: allow teardown.
  deletion_protection = false

  project  = var.project_id
  name     = var.job_name
  location = var.region

  template {
    # Job-level: one task per execution, no parallelism. The D58 query-based dedup
    # is single-instance only, and one trigger is one task.
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.square_connector.email

      # A failed pull surfaces as a failed execution. Safe to raise (the dedup
      # collapses a same-run_key retry), but a silent retry hides the first failure.
      max_retries = var.max_retries
      timeout     = var.task_timeout

      # Egress to the private Cloud SQL IP via the Thalamus connector.
      # PRIVATE_RANGES_ONLY keeps public egress (Square, Pub/Sub, GCS, Secret
      # Manager) off the connector.
      vpc_access {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image = var.image

        # NO command and NO args. The image's ENTRYPOINT is
        # `python -m thalamus_square.real_transport`; the run target arrives per
        # execution as `gcloud run jobs execute --args=...`. Setting args here
        # would bake a tenant into a multi-tenant connector.

        resources {
          limits = {
            cpu    = var.cpu
            memory = var.memory
          }
        }

        # Plain env vars.
        dynamic "env" {
          for_each = local.plain_env
          content {
            name  = env.key
            value = env.value
          }
        }

        # Secret env vars (VALUE by reference only, never inline).
        env {
          name = "POSTGRES_URL" # sdk/config.py:38 required at boot; secret-backed
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.database_url.secret_id
              version = "latest"
            }
          }
        }

        env {
          name = "SQUARE_APP_SECRET" # config.py:82; the Square client_secret, never logged
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.square_app_secret.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.database_url,
    google_secret_manager_secret_iam_member.square_app_secret,
    google_project_iam_member.square_token_vault_refresher,
    google_storage_bucket_iam_member.bronze_object_admin,
    google_pubsub_topic_iam_member.ingress_publisher,
  ]
}

# No invoker IAM binding here. Executions are operator-run (`gcloud run jobs
# execute`) under the caller's own credentials; run.invoker on the job is granted
# per-principal out of band when a scheduler or workflow starts triggering it.
