###############################################################################
# cloud-run-service-clover-connector: the Thalamus Clover connector on the
# Thalamus data plane.
#
# A Cloud Run JOB, not a Service. One execution is ONE trigger: the container
# runs python -m thalamus_clover.real_transport, which mints the producer-owned
# ids, builds a ConnectorTrigger and runs a single Clover catalog pull
# (extract -> CSV -> bronze -> ingress.ready), then exits. There is no loop, no
# server, no port and no health probe.
#
# Shape adapted from infra/modules/cloud-run-service-square-connector, with:
#   1. cloverTokenVaultRefresher carries FIVE permissions, not Square's three:
#      versions.list and versions.destroy are added for the D5 version prune.
#      Clover access tokens live 30 MINUTES, so a rotating connector would
#      accumulate ~24 secret versions per merchant per day; CloverTokenVault
#      prunes to current+previous on every write. Square has no prune.
#   2. CLOVER_API_BASE_URL, not SQUARE_API_BASE_URL, and its default skew is
#      minutes rather than days for the same 30-minute-token reason.
#   3. No dis-canonical and only csv-ingest-worker among the dis services in the
#      image (see the Dockerfile header) - a smaller closure than Square's.
#
# SQUARE'S ROLE MUST NOT BE WIDENED TO MATCH THIS ONE. The naming here is
# vendor-specific and that is CORRECT, unlike the BFF's. The BFF holds ONE role
# serving every vendor's vault, so a vendor name there was a lie and was renamed
# to tokenVaultWriter. Connector SAs are per-vendor with genuinely different
# needs: the Square connector has no prune and must keep three permissions.
# "Harmonising" the two roles would hand the Square SA a destroy permission it
# has no code path for.
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
#   - secretmanager.secrets.create: withheld from cloverTokenVaultRefresher.
#     GoogleSecretBackend.add_version falls back to create_secret on NotFound,
#     but that fallback is UNREACHABLE for this SA: the only caller is
#     CloverTokenStore.get_session, which reads the vault FIRST and raises
#     CloverOAuthNotConnectedError when the secret is absent, so the write path
#     is never reached without an existing secret. Creating token secrets is the
#     BFF's job (tokenVaultWriter on cloud-run-service-dis-ui-server).
#   - roles/secretmanager.secretAccessor at project level: too broad. The two
#     named secrets are resource-scoped grants; the per-tenant token vault gets
#     the narrow custom role instead.
#   - An IAM condition on cloverTokenVaultRefresher. A name-prefix condition
#     (resource.name.startsWith(".../secrets/clover-oauth-")) is the available
#     tightening and applies equally to the Square refresher and the BFF's
#     writer. Deliberately deferred so all three stay consistent: conditioning
#     one while its neighbours are unconditioned is worse than conditioning none.
###############################################################################

# Dedicated runtime identity for the connector job.
resource "google_service_account" "clover_connector" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "Thalamus clover-connector Cloud Run job runtime SA"
}

# Existing secrets (created out of band). Data sources resolve the ids for the
# IAM grants below and fail the plan fast if a secret is missing.
data "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = var.secret_database_url
}

data "google_secret_manager_secret" "clover_app_secret" {
  project   = var.project_id
  secret_id = var.secret_clover_app_secret
}

# Least-privilege runtime grants, resource-scoped where the resource supports it.
resource "google_secret_manager_secret_iam_member" "database_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.clover_connector.email}"
}

# The Clover app secret. The REFRESH leg does not send one, but the RECOVERY leg
# (D4) does, and recovery is what saves a merchant after a lost write. Starting
# without it would work for weeks and then fail exactly when it matters most.
resource "google_secret_manager_secret_iam_member" "clover_app_secret" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.clover_app_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.clover_connector.email}"
}

# The per-tenant Clover OAuth token vault: one secret per (tenant, source), named
# clover-oauth-{tenant_uuid}-{slug}-{hash8} (thalamus_clover_oauth/naming.py) and
# MINTED AT OAUTH-COMPLETE TIME by the BFF. The names therefore do not exist when
# this plan runs and cannot be resource-scoped, so this is a narrow project-scoped
# custom role rather than roles/secretmanager.secretAccessor at project level.
#
# versions.add is REQUIRED: CloverTokenStore rotates when the access token is
# within the skew of expiry and PERSISTS the rotated pair BEFORE returning it
# (D2). Clover refresh tokens are SINGLE-USE, so a failed persist does not cost a
# round trip as it would on Square - it strands the merchant.
#
# versions.list and versions.destroy are the D5 PRUNE, and the prune is part of
# the write path, not a maintenance job. Without them the write succeeds and the
# prune fails with PermissionDenied while the run looks healthy - exactly what
# happened to the BFF today, where enabled versions reached four against a
# keep-two policy.
resource "google_project_iam_custom_role" "clover_token_vault_refresher" {
  project     = var.project_id
  role_id     = "cloverTokenVaultRefresher"
  title       = "Clover token vault refresher (clover-connector)"
  description = "Read, refresh-and-persist, and prune the per-tenant Clover OAuth token secrets."
  permissions = [
    "secretmanager.secrets.get",
    "secretmanager.versions.access",
    "secretmanager.versions.add",
    "secretmanager.versions.destroy",
    "secretmanager.versions.list",
  ]
}

resource "google_project_iam_member" "clover_token_vault_refresher" {
  project = var.project_id
  role    = google_project_iam_custom_role.clover_token_vault_refresher.id
  member  = "serviceAccount:${google_service_account.clover_connector.email}"
}

# The connector PRODUCES the bronze object (CSV serialized from the Clover pull),
# so objectAdmin - not the streaming-consumer's read-only objectViewer.
resource "google_storage_bucket_iam_member" "bronze_object_admin" {
  bucket = var.bronze_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.clover_connector.email}"
}

resource "google_pubsub_topic_iam_member" "ingress_publisher" {
  project = var.project_id
  topic   = var.ingress_topic_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.clover_connector.email}"
}

locals {
  # Plain env. Names are the EXACT vars the connector's config resolves.
  # REQUIRED at boot: PUBSUB_PROJECT_ID, GCS_BUCKET_BRONZE (SdkConfig.from_env) and
  # CLOVER_CLIENT_ID / CLOVER_SECRETS_PROJECT_ID (CloverOAuthEnv.from_env, reached
  # only because real_transport injects no token_store). POSTGRES_URL and
  # CLOVER_APP_SECRET are secret env, below.
  #
  # CLOVER_OAUTH_REDIRECT_URI is deliberately ABSENT: the connector never runs the
  # authorize leg, CloverOAuthEnv does not read it, and pipeline.py passes
  # redirect_uri="" to the client.
  #
  # STORAGE_EMULATOR_HOST and PUBSUB_EMULATOR_HOST are deliberately ABSENT: both
  # clients are emulator-or-ambient and would silently redirect off GCP if set.
  # CLOVER_OAUTH_REFRESH_SKEW_SECONDS is left UNSET: the in-code 5-minute default
  # is the intent for a 30-minute token. There is no RUN_HEALTH_SERVER/PORT.
  plain_env = {
    DIS_EXPECTED_DATABASE = var.dis_expected_database # dis-rls guard (session.py:52); "thalamus", NOT the ithina_dis_db default
    PUBSUB_PROJECT_ID     = var.project_id            # sdk/config.py:43 required at boot
    GCS_BUCKET_BRONZE     = var.bronze_bucket_name    # sdk/config.py:46 required at boot (written)
    # INGRESS_READY_TOPIC is resolved at IMPORT time as a module constant
    # (csv_ingest_worker/config.py:57, default "ingress.ready") and the SDK pipeline
    # publishes to it directly. It MUST name the provisioned topic, or the connector
    # publishes to a topic that does not exist AFTER the bronze write has landed.
    INGRESS_READY_TOPIC = var.ingress_ready_topic
    # The Clover host: the API base AND the OAuth base for the refresh/recovery legs
    # AND the environment stamp. CloverOAuthClient derives
    # environment = "sandbox" if "sandbox" in base_url else "production" at
    # construction (client.py:114) and writes it onto every rotated token record
    # (client.py:233). The BFF stamps the SAME field from its own
    # CLOVER_OAUTH_BASE_URL, so staging feeds both from ONE env-level variable -
    # see infra/envs/staging/variables.tf. Nothing reads the stamp today, but two
    # writers of one field must not be able to disagree.
    CLOVER_API_BASE_URL       = var.clover_api_base_url # config.py:47
    CLOVER_CLIENT_ID          = var.clover_client_id    # oauth_config.py:45 required on the real path
    CLOVER_SECRETS_PROJECT_ID = var.project_id          # oauth_config.py:53 the token vault's project
  }
}

resource "google_cloud_run_v2_job" "clover_connector" {
  # Staging: allow teardown.
  deletion_protection = false

  project  = var.project_id
  name     = var.job_name
  location = var.region

  template {
    # Job-level: one task per execution, no parallelism. The D58 query-based dedup
    # is single-instance only, and one trigger is one task. It matters more here
    # than on Square: Clover refresh tokens are single-use, so two concurrent
    # rotations for one merchant produce two chains and one of them is dead.
    task_count  = 1
    parallelism = 1

    template {
      service_account = google_service_account.clover_connector.email

      # A failed pull surfaces as a failed execution. Safe to raise (the dedup
      # collapses a same-run_key retry), but a silent retry hides the first failure.
      max_retries = var.max_retries
      timeout     = var.task_timeout

      # Egress to the private Cloud SQL IP via the Thalamus connector.
      # PRIVATE_RANGES_ONLY keeps public egress (Clover, Pub/Sub, GCS, Secret
      # Manager) off the connector.
      vpc_access {
        connector = var.vpc_connector_id
        egress    = "PRIVATE_RANGES_ONLY"
      }

      containers {
        image = var.image

        # NO command and NO args. The image's ENTRYPOINT is
        # `python -m thalamus_clover.real_transport`; the run target arrives per
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
          name = "CLOVER_APP_SECRET" # oauth_config.py:48; the recovery leg needs it
          value_source {
            secret_key_ref {
              secret  = data.google_secret_manager_secret.clover_app_secret.secret_id
              version = "latest"
            }
          }
        }
      }
    }
  }

  depends_on = [
    google_secret_manager_secret_iam_member.database_url,
    google_secret_manager_secret_iam_member.clover_app_secret,
    google_project_iam_member.clover_token_vault_refresher,
    google_storage_bucket_iam_member.bronze_object_admin,
    google_pubsub_topic_iam_member.ingress_publisher,
  ]
}

# No invoker IAM binding here. Executions are operator-run (`gcloud run jobs
# execute`) under the caller's own credentials; run.invoker on the job is granted
# per-principal out of band when a scheduler or workflow starts triggering it.
