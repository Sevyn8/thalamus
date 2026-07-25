###############################################################################
# cloud-run-service-dis-ui-server: the DIS UI backend-for-frontend
# (dis-ui-server) Cloud Run v2 service on the Thalamus data plane.
#
# Shape adapted from infra/modules/cloud-run-service-cm (the proven CM deploy):
# dedicated SA, connector egress PRIVATE_RANGES_ONLY, ingress ALL,
# authenticated-only (NO allUsers binding; the org's
# iam.allowedPolicyMemberDomains policy blocks it and a public backend is the
# wrong posture), startup probe on the health path, secret-backed DB URL.
#
# Divergences from the CM module:
#   1. DB name guard: DIS_EXPECTED_DATABASE=thalamus (the parameterized dis-rls
#      guard). Without it /readyz fails against the shared "thalamus" database.
#   2. Health path is /healthz (DB-free liveness), not /api/v1/health.
#   3. Two extra runtime grants: storage.objectAdmin on the bronze bucket (CSV
#      upload writes) and pubsub.publisher on the csv.received topic (the
#      csv.received publish). One DB secret (dis-database-url), not three.
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
  }
}

resource "google_cloud_run_v2_service" "dis_ui_server" {
  # Staging: allow teardown.
  deletion_protection = false

  project  = var.project_id
  name     = var.service_name
  location = var.region

  # Ingress ALL = the URL is reachable at the network layer. This does NOT make
  # the service public: run.invoker IAM (granted per-principal out of band) gates
  # who can call it, and the app's own auth guards data endpoints on top.
  ingress = "INGRESS_TRAFFIC_ALL"

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
    google_storage_bucket_iam_member.bronze_object_admin,
    google_pubsub_topic_iam_member.csv_publisher,
  ]
}

# No invoker IAM binding here. dis-ui-server is authenticated-only: run.invoker
# is granted per-principal out of band. allUsers / allAuthenticatedUsers are
# rejected by the org's iam.allowedPolicyMemberDomains policy and are the wrong
# posture for a backend regardless.
