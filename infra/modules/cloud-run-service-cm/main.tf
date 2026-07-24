###############################################################################
# cloud-run-service-cm: the CM (cm-backend) Cloud Run v2 service on the
# Thalamus data plane, in AUTH0 mode.
#
# Shape adapted from infra/_import/cm-infra/terraform/modules/cloud-run-backend
# with three deliberate divergences for Thalamus staging:
#   1. VPC egress is via the Serverless VPC Access CONNECTOR (thalamus-vpcconn),
#      not direct network_interfaces. PRIVATE_RANGES_ONLY so only RFC1918
#      traffic (the private Cloud SQL IP 10.55.0.3) rides the connector; Auth0
#      and SendGrid (public) take the default internet egress path.
#   2. AUTH0 mode, not STUB. No JWT key-file volumes (those were stub-only);
#      CM verifies tokens against Auth0's JWKS.
#   3. Image is managed by Terraform directly (real v1 tag), not a placeholder
#      overwritten by `gcloud run deploy`.
#
# NOT granted here, by design:
#   - roles/cloudsql.client: CM connects to Cloud SQL over the private IP at the
#     TCP layer (DATABASE_URL host = 10.55.0.3, sslmode=require) through the VPC
#     connector. The Cloud SQL IAM client role is only needed for the Auth Proxy
#     / connector-auth path, which this deployment does not use.
#   - Artifact Registry reader: image pulls use the Cloud Run service agent
#     (service-<num>@serverless-robot-prod...), which has repo read access by
#     default for images in the same project. The runtime SA does not pull.
###############################################################################

# Dedicated runtime identity for the service.
resource "google_service_account" "cm_backend" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "CM backend (cm-backend) Cloud Run runtime SA"
}

# Existing secrets (created out-of-band this session). Data sources both resolve
# the secret ids for the IAM grants below and fail the plan fast if a secret is
# missing.
data "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = var.secret_database_url
}

data "google_secret_manager_secret" "auth0_mgmt_client_secret" {
  project   = var.project_id
  secret_id = var.secret_auth0_mgmt_client_secret
}

data "google_secret_manager_secret" "sendgrid_api_key" {
  project   = var.project_id
  secret_id = var.secret_sendgrid_api_key
}

# Least-privilege: the runtime SA gets secretAccessor on exactly the three
# cm-* secrets, not a project-wide grant.
resource "google_secret_manager_secret_iam_member" "database_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cm_backend.email}"
}

resource "google_secret_manager_secret_iam_member" "auth0_mgmt_client_secret" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.auth0_mgmt_client_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cm_backend.email}"
}

resource "google_secret_manager_secret_iam_member" "sendgrid_api_key" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.sendgrid_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.cm_backend.email}"
}

locals {
  # Plain env, always set. Names are CM's EXACT config.py field names (upper-cased;
  # pydantic-settings is case_sensitive=False). See config.py:75-154.
  base_env = {
    DB_SCHEMA           = var.db_schema           # config.py:87  db_schema
    AUTH_CLIENT_MODE    = "AUTH0"                  # config.py:90  auth_client_mode
    JWT_ISSUER          = var.jwt_issuer           # config.py:92  jwt_issuer
    JWT_AUDIENCE        = var.jwt_audience         # config.py:92  jwt_audience
    AUTH0_JWKS_URL      = var.auth0_jwks_url       # config.py:102 auth0_jwks_url
    APP_REGION          = var.app_region           # config.py:135 app_region (EU|US|LOCAL)
    ENVIRONMENT         = var.environment          # config.py:136 environment
    LOG_LEVEL           = var.log_level            # config.py:137 log_level
    SENDGRID_FROM_EMAIL  = var.sendgrid_from_email  # config.py:125 sendgrid_from_email
    CORS_ALLOWED_ORIGINS = var.cors_allowed_origins # config.py:141 cors_allowed_origins
  }

  # Lazy Auth0 values. Empty string => omit the env var entirely so CM's
  # `str | None` fields resolve to None (not ""), matching the lazy-optional
  # posture the Auth0 Management / SendGrid clients expect.
  optional_env = {
    AUTH0_MGMT_CLIENT_ID     = var.auth0_mgmt_client_id     # config.py:115 auth0_mgmt_client_id
    AUTH0_MGMT_DB_CONNECTION = var.auth0_mgmt_db_connection # config.py:132 auth0_mgmt_db_connection
    AUTH0_TICKET_RESULT_URL  = var.auth0_ticket_result_url  # config.py:126 auth0_ticket_result_url
  }

  plain_env = merge(
    local.base_env,
    { for k, v in local.optional_env : k => v if v != "" },
  )
}

resource "google_cloud_run_v2_service" "cm_backend" {
  # Staging: allow teardown.
  deletion_protection = false

  project  = var.project_id
  name     = var.service_name
  location = var.region

  # Ingress ALL = the URL is reachable at the network layer. This does NOT make
  # the service public: run.invoker IAM (granted per-principal out of band) gates
  # who can call it, and app-level JWT guards every data endpoint on top.
  ingress = "INGRESS_TRAFFIC_ALL"

  template {
    service_account = google_service_account.cm_backend.email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    # Egress to the private Cloud SQL IP via the Thalamus connector.
    # PRIVATE_RANGES_ONLY keeps public egress (Auth0, SendGrid) off the connector.
    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    containers {
      image = var.image

      # CM honors $PORT (Cloud Run injects PORT); Dockerfile EXPOSE 8080.
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

      # Secret env vars (VALUES by reference only, never inline).
      env {
        name = "DATABASE_URL" # config.py:86 database_url
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "AUTH0_MGMT_CLIENT_SECRET" # config.py:116 auth0_mgmt_client_secret
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.auth0_mgmt_client_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "SENDGRID_API_KEY" # config.py:124 sendgrid_api_key
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.sendgrid_api_key.secret_id
            version = "latest"
          }
        }
      }

      # Liveness path: /api/v1/health (main.py:191; no DB, returns 200 fast).
      startup_probe {
        http_get {
          path = "/api/v1/health"
          port = 8080
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 12 # ~60s cold-start budget
        timeout_seconds       = 3
      }

      liveness_probe {
        http_get {
          path = "/api/v1/health"
          port = 8080
        }
        period_seconds    = 30
        failure_threshold = 3
        timeout_seconds   = 3
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
    google_secret_manager_secret_iam_member.auth0_mgmt_client_secret,
    google_secret_manager_secret_iam_member.sendgrid_api_key,
  ]
}

# No invoker IAM binding here. CM is authenticated-only: run.invoker is granted
# per-principal out of band (e.g. an operator user for testing, DIS's SA for
# service-to-service later). allUsers is also rejected by the org's
# iam.allowedPolicyMemberDomains (Domain Restricted Sharing) policy, and a
# public backend is the wrong posture regardless.
