###############################################################################
# cloud-run-service-dis-ui-server: the DIS UI backend-for-frontend
# (dis-ui-server) Cloud Run v2 service on the Thalamus data plane.
#
# Shape adapted from infra/modules/cloud-run-service-cm (the proven CM deploy):
# dedicated SA, connector egress PRIVATE_RANGES_ONLY, ingress ALL, startup probe
# on the health path, secret-backed DB URL.
#
# PUBLIC AT THE NETWORK LAYER. This service carries an `allUsers`
# roles/run.invoker binding (declared and imported at the bottom of this file), so
# Cloud Run performs NO IAM check on inbound requests and the Auth0 JWT that
# dis-ui-server verifies in-process is the SOLE gate. Not defence-in-depth: there
# is no layer beneath it. An endpoint that forgets its auth guard is
# world-readable, not merely a bug behind a locked door.
#
# This header previously claimed the opposite - "authenticated-only (NO allUsers
# binding; the org's iam.allowedPolicyMemberDomains policy blocks it)". Both
# halves were false: the binding is live, and that policy is listPolicy
# allValues=ALLOW on this project, directly and effectively, so it blocks nothing
# and never did.
#
# Divergences from the CM module:
#   1. DB name guard: DIS_EXPECTED_DATABASE=thalamus (the parameterized dis-rls
#      guard). Without it /readyz fails against the shared "thalamus" database.
#   2. Health path is /healthz (DB-free liveness), not /api/v1/health.
#   3. Two extra runtime grants: storage.objectAdmin on the bronze bucket (CSV
#      upload writes) and pubsub.publisher on the csv.received topic (the
#      csv.received publish). One DB secret (dis-database-url), not three.
#   4. TWO vendor OAuth connect flows, Square (S2) and Clover (C3), each with its
#      own client id / redirect / app secret. The state-signing key is SHARED and
#      belongs to neither: one secret, one env var, both vendors.
#
# tokenVaultWriter SERVES EVERY VENDOR'S TOKEN VAULT. It is project-level and
# unconditioned because the per-tenant secret names are minted at OAuth-complete time
# (square-oauth-* / clover-oauth-*) and cannot be resource-scoped at plan time.
#
# THE LAST TWO PERMISSIONS ARE THE D5 VERSION PRUNE, and they are on the WRITER
# deliberately: the prune is not a separate maintenance job, it IS part of the write
# path. Clover access tokens live 30 minutes, so a rotating connector would otherwise
# accumulate ~24 secret versions per merchant per day.
#
# THE PREVIOUS NAME IS WHY THIS WAS UNDER-SCOPED. The role was called
# squareTokenVaultWriter and sized for Square, which has no prune. Read while
# reasoning about a second vendor, a vendor-specific name invited the conclusion that
# it already covered Clover - it covered the WRITES and nothing else, and Clover's
# prune failed in production with PermissionDenied on versions.list while the connect
# itself appeared to succeed. The name is now vendor-neutral so the next vendor is
# reasoned about on the permissions, not the label.
#
# NOT granted here, by design:
#   - roles/cloudsql.client: dis-ui-server connects over the private IP at the
#     TCP layer (POSTGRES_URL host = 10.55.0.3, sslmode=require) through the VPC
#     connector. No socket/proxy is used anywhere in the service.
#   - Artifact Registry reader: image pulls use the Cloud Run service agent,
#     which reads same-project repos by default. The runtime SA does not pull.
###############################################################################

# Dedicated runtime identity for the service.
resource "google_service_account" "dis_ui_server" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "DIS ui-server (dis-ui-server) Cloud Run runtime SA"
}

# Existing secret (created out of band). Data source resolves the id for the
# IAM grant below and fails the plan fast if the secret is missing.
data "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = var.secret_database_url
}

# Least-privilege runtime grants, resource-scoped (not project-wide).
resource "google_secret_manager_secret_iam_member" "database_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.dis_ui_server.email}"
}

# --- Square OAuth connect (S2) ---
# The app secret and the state-signing key are secret-backed env (created out of band).
# Data sources resolve their ids for the IAM grants and fail the plan fast if missing.
data "google_secret_manager_secret" "square_app_secret" {
  project   = var.project_id
  secret_id = var.secret_square_app_secret
}

data "google_secret_manager_secret" "oauth_state_key" {
  project   = var.project_id
  secret_id = var.secret_oauth_state_key
}

resource "google_secret_manager_secret_iam_member" "square_app_secret" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.square_app_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.dis_ui_server.email}"
}

resource "google_secret_manager_secret_iam_member" "oauth_state_key" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.oauth_state_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.dis_ui_server.email}"
}

# --- Clover OAuth connect (C3) ---
# Same shape as the Square block above. The state-signing key is NOT duplicated: it is
# shared across vendors and already granted above.
data "google_secret_manager_secret" "clover_app_secret" {
  project   = var.project_id
  secret_id = var.secret_clover_app_secret
}

resource "google_secret_manager_secret_iam_member" "clover_app_secret" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.clover_app_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.dis_ui_server.email}"
}

# The callback creates one Secret Manager secret per tenant/source and adds versions to it.
# secretmanager.secrets.create is a PROJECT-level permission (cannot be resource-scoped), so
# this is a narrow project-scoped custom role rather than roles/secretmanager.admin.
resource "google_project_iam_custom_role" "token_vault_writer" {
  project     = var.project_id
  role_id     = "tokenVaultWriter"
  title       = "Token vault writer (dis-ui-server, all vendors)"
  description = "Create, add, access and PRUNE the per-tenant OAuth token secrets for every vendor (square-oauth-* / clover-oauth-*)."
  permissions = [
    "secretmanager.secrets.create",
    "secretmanager.secrets.get",
    "secretmanager.versions.access",
    "secretmanager.versions.add",
    # The D5 prune. Without these the vault write succeeds and the prune fails with
    # PermissionDenied, so versions accumulate silently behind a healthy-looking connect.
    "secretmanager.versions.list",
    "secretmanager.versions.destroy",
  ]
}

resource "google_project_iam_member" "token_vault_writer" {
  project = var.project_id
  role    = google_project_iam_custom_role.token_vault_writer.id
  member  = "serviceAccount:${google_service_account.dis_ui_server.email}"
}

resource "google_storage_bucket_iam_member" "bronze_object_admin" {
  bucket = var.bronze_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.dis_ui_server.email}"
}

resource "google_pubsub_topic_iam_member" "csv_publisher" {
  project = var.project_id
  topic   = var.csv_topic_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.dis_ui_server.email}"
}

locals {
  # Plain env. Names are the EXACT vars dis-ui-server config.py reads. REQUIRED
  # at boot: GCS_BUCKET_BRONZE, PUBSUB_PROJECT_ID (POSTGRES_URL is secret env).
  # DIS_EXPECTED_DATABASE is required for /readyz (the dis-rls guard).
  # CORS_ALLOWED_ORIGINS and GEMINI_* are deliberately UNSET (the app raises on
  # CORS set-but-empty; GEMINI unset -> mechanical fallback).
  plain_env = {
    DIS_EXPECTED_DATABASE = var.dis_expected_database # parameterized dis-rls guard
    GCS_BUCKET_BRONZE     = var.bronze_bucket_name    # config.py:63 required at boot
    PUBSUB_PROJECT_ID     = var.project_id            # config.py:64 required at boot
    CSV_RECEIVED_TOPIC    = var.csv_received_topic    # config.py:83 (defaults csv.received; set to provisioned name)
    DIS_AUTH_MODE         = var.dis_auth_mode         # AUTH0 -> RS256/JWKS verifier (real Auth0 tokens)
    JWT_ISSUER            = var.jwt_issuer            # Auth0 issuer; backend derives AUTH0_JWKS_URL from it
    JWT_AUDIENCE          = var.jwt_audience          # DIS API audience
    # Square OAuth connect (S2). config.py reads these; unset -> the OAuth endpoints 503.
    # SQUARE_APP_SECRET + STATE_SIGNING_KEY are secret env (below), never plain.
    SQUARE_CLIENT_ID          = var.square_client_id          # Square application id (public)
    SQUARE_OAUTH_BASE_URL     = var.square_oauth_base_url     # sandbox host default
    SQUARE_OAUTH_REDIRECT_URI = var.square_oauth_redirect_uri # exact URL registered at Square
    SQUARE_SECRETS_PROJECT_ID = var.project_id                # token vault lives in this project
    # Clover OAuth connect (C3). config.py reads these; unset -> the Clover endpoints 503.
    # CLOVER_APP_SECRET is secret env (below), never plain. CLOVER_SECRETS_PROJECT_ID is
    # left unset and defaults to the pubsub project, exactly as Square's does.
    CLOVER_CLIENT_ID = var.clover_client_id # Clover application id (public)
    # SET EXPLICITLY, not left to the config default, because this is not merely a host:
    # thalamus_clover_oauth derives environment = "sandbox" if "sandbox" in base_url else
    # "production" at client construction and STAMPS IT ONTO EVERY STORED TOKEN RECORD.
    # A silent default deciding a credential's environment is the same shape as
    # SQUARE_API_BASE_URL on the connector side. Clover hosts are per-REGION as well as
    # per-environment, so production must set this deliberately.
    CLOVER_OAUTH_BASE_URL = var.clover_oauth_base_url
    # The LAUNCH path, not the callback: launch is the redirect_uri empirically proven
    # accepted by Clover, and Clover requires the value to match a URL registered in the
    # dashboard. CloverCallback forwards to CloverLaunch, so routing loses nothing.
    CLOVER_OAUTH_REDIRECT_URI = var.clover_oauth_redirect_uri
  }
}

resource "google_cloud_run_v2_service" "dis_ui_server" {
  # Staging: allow teardown.
  deletion_protection = false

  project  = var.project_id
  name     = var.service_name
  location = var.region

  # Ingress ALL = the URL is reachable at the network layer, and for THIS service
  # that does mean publicly callable: the allUsers invoker binding at the bottom of
  # this file is live, so nothing gates the request before the app sees it. The
  # previous wording here said "This does NOT make the service public", which was
  # the third instance of the same false claim in this file.
  ingress = "INGRESS_TRAFFIC_ALL"

  # SERVICE-LEVEL scaling, not the per-revision block in template below (the real
  # floor is template.scaling, untouched). Do not delete as redundant: the v2 API
  # returns maxInstanceCount, which the provider cannot represent, so it fills its
  # three known attributes with zeros - an undeclared block diffs 0 -> null forever.
  scaling {
    min_instance_count    = 0
    manual_instance_count = 0
  }

  template {
    service_account = google_service_account.dis_ui_server.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # Egress to the private Cloud SQL IP via the Thalamus connector.
    # PRIVATE_RANGES_ONLY keeps public egress (Pub/Sub, GCS) off the connector.
    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.image

      # dis-ui-server Dockerfile hardcodes uvicorn --port 8080 (matches the
      # Cloud Run default injected PORT). Do not set a different port.
      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      # Plain env vars.
      dynamic "env" {
        for_each = local.plain_env
        content {
          name  = env.key
          value = env.value
        }
      }

      # Secret env var (VALUE by reference only, never inline).
      env {
        name = "POSTGRES_URL" # config.py:61 required at boot; secret-backed
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }

      # Square OAuth secrets (S2): value by reference only, never inline.
      env {
        name = "SQUARE_APP_SECRET" # the Square client_secret; never logged
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.square_app_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "CLOVER_APP_SECRET" # the Clover app secret; never logged
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.clover_app_secret.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "STATE_SIGNING_KEY" # HMAC key signing the OAuth state token (SHARED: both vendors)
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.oauth_state_key.secret_id
            version = "latest"
          }
        }
      }

      # Liveness path: /healthz (handlers/health.py:38; DB-free, returns 200
      # fast). NOT /readyz (which opens the dis-rls session and needs the DB).
      startup_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 12 # ~60s cold-start budget
        timeout_seconds       = 3
      }
    }

    timeout = "60s"
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  depends_on = [
    google_secret_manager_secret_iam_member.database_url,
    google_secret_manager_secret_iam_member.square_app_secret,
    google_secret_manager_secret_iam_member.oauth_state_key,
    google_secret_manager_secret_iam_member.clover_app_secret,
    google_storage_bucket_iam_member.bronze_object_admin,
    google_pubsub_topic_iam_member.csv_publisher,
  ]
}

# PUBLIC invoker binding, declared because it is LIVE and imported so Terraform can
# see it. An out-of-band grant Terraform cannot see is worse than a visible one: it
# does not appear in a plan, a diff, or a review, so nobody can notice it changing.
#
# THE POSTURE, PLAINLY: allUsers holds roles/run.invoker, so Cloud Run performs no
# IAM check and the Auth0 JWT dis-ui-server verifies in-process is the SOLE gate on
# every endpoint. There is no network layer beneath it to fall back on.
#
# This block previously read "No invoker IAM binding here. dis-ui-server is
# authenticated-only: run.invoker is granted per-principal out of band. allUsers /
# allAuthenticatedUsers are rejected by the org's iam.allowedPolicyMemberDomains
# policy". Every clause was wrong: the binding exists, it is allUsers rather than
# per-principal, and the policy is allValues=ALLOW (direct and effective) so it
# rejects nothing.
#
# DO NOT TIGHTEN THIS WITHOUT READING cloud-run-service-dis-ui-ver2/main.tf FIRST.
# ver2's nginx reverse-proxies /api to this service carrying only the browser's
# Auth0 bearer and no credential of its own, so removing this binding breaks every
# /api call through the DIS UI with an immediate 403 while the page still loads.
# The full explanation is the COUPLING block at the top of that module; it is not
# repeated here so there is one copy to keep true.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.dis_ui_server.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
