###############################################################################
# cloud-run-service-csv-ingest-worker: the DIS csv-ingest-worker on the
# Thalamus data plane.
#
# A long-running Pub/Sub PULL consumer deployed as an always-on Cloud Run
# Service: RUN_HEALTH_SERVER=true serves /healthz for the Cloud Run probe while
# subscriber.run_forever() pulls csv.received in a sibling task. NOT a push
# subscription: no OIDC push-invoker, no allUsers.
#
# Shape adapted from infra/modules/cloud-run-service-dis-ui-server, with:
#   1. D58 single-instance CORRECTNESS constraint: min=max=1, cpu_idle=false
#      (CPU always allocated so the pull loop runs when no request is in flight).
#      The query-based dedup is single-instance only; do not scale.
#   2. Pub/Sub grants: pubsub.subscriber on the csv.received subscription,
#      pubsub.publisher on the ingress.ready topic, and pubsub.viewer at project
#      level (the startup _require_subscription preflight calls subscriptions.get).
#   3. storage.objectAdmin on bronze (reads the uploaded object). One DB secret.
#
# NOT granted here, by design:
#   - roles/cloudsql.client: connects over the private IP at the TCP layer
#     (POSTGRES_URL host = 10.55.0.3, sslmode=require) through the VPC connector.
#     No socket/proxy is used anywhere in the worker.
#   - Artifact Registry reader: image pulls use the Cloud Run service agent.
###############################################################################

# Dedicated runtime identity for the worker.
resource "google_service_account" "csv_ingest_worker" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "DIS csv-ingest-worker Cloud Run runtime SA"
}

# Existing secret (created out of band). Data source resolves the id for the
# IAM grant below and fails the plan fast if the secret is missing.
data "google_secret_manager_secret" "database_url" {
  project   = var.project_id
  secret_id = var.secret_database_url
}

# Least-privilege runtime grants, resource-scoped where the resource supports it.
resource "google_secret_manager_secret_iam_member" "database_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.database_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.csv_ingest_worker.email}"
}

resource "google_storage_bucket_iam_member" "bronze_object_admin" {
  bucket = var.bronze_bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.csv_ingest_worker.email}"
}

resource "google_pubsub_subscription_iam_member" "csv_subscriber" {
  project      = var.project_id
  subscription = var.subscription_id
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.csv_ingest_worker.email}"
}

resource "google_pubsub_topic_iam_member" "ingress_publisher" {
  project = var.project_id
  topic   = var.ingress_topic_id
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.csv_ingest_worker.email}"
}

# pubsub.viewer at project level: the worker's startup _require_subscription
# preflight calls subscriptions.get, which is in roles/pubsub.viewer and is not
# covered by pubsub.subscriber. Without it the worker errors at startup.
resource "google_project_iam_member" "pubsub_viewer" {
  project = var.project_id
  role    = "roles/pubsub.viewer"
  member  = "serviceAccount:${google_service_account.csv_ingest_worker.email}"
}

locals {
  # Plain env. Names are the EXACT vars csv-ingest-worker config.py reads.
  # REQUIRED at boot: PUBSUB_PROJECT_ID, GCS_BUCKET_BRONZE (POSTGRES_URL is
  # secret env; PORT is Cloud-Run-injected when RUN_HEALTH_SERVER is on).
  # DIS_EXPECTED_DATABASE is the dis-rls guard for the bronze write path.
  plain_env = {
    DIS_EXPECTED_DATABASE     = var.dis_expected_database     # parameterized dis-rls guard
    PUBSUB_PROJECT_ID         = var.project_id                # config.py:42 required at boot
    GCS_BUCKET_BRONZE         = var.bronze_bucket_name        # config.py:43 required at boot
    RUN_HEALTH_SERVER         = "true"                        # Cloud Run Service mode: serve /healthz
    CSV_RECEIVED_SUBSCRIPTION = var.csv_received_subscription # config.py:58 the pull subscription
    INGRESS_READY_TOPIC       = var.ingress_ready_topic       # config.py:57 the publish target
  }
}

resource "google_cloud_run_v2_service" "csv_ingest_worker" {
  # Staging: allow teardown.
  deletion_protection = false

  project  = var.project_id
  name     = var.service_name
  location = var.region

  # Ingress ALL = the URL is reachable at the network layer (for the /healthz
  # probe). This does NOT make the service public: no invoker IAM is bound, and
  # the worker's real work is an outbound pull loop, not inbound requests.
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
    service_account = google_service_account.csv_ingest_worker.email

    # D58: pinned to exactly one instance (query-based dedup is single-instance).
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

      # The worker's /healthz server binds the Cloud-Run-injected $PORT (8080).
      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        # cpu_idle=false: CPU stays allocated so the background pull loop keeps
        # consuming when no HTTP request (only the /healthz probe) is in flight.
        # A CPU-throttled idle instance would stop pulling. D58 / D83.
        cpu_idle          = false
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
        name = "POSTGRES_URL" # config.py:41 required at boot; secret-backed
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.database_url.secret_id
            version = "latest"
          }
        }
      }

      # Readiness server path: /healthz (served when RUN_HEALTH_SERVER=true).
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
    google_pubsub_subscription_iam_member.csv_subscriber,
    google_pubsub_topic_iam_member.ingress_publisher,
    google_project_iam_member.pubsub_viewer,
  ]
}

# No invoker IAM binding here. The worker is authenticated-only (its real work is
# an outbound pull loop). allUsers / allAuthenticatedUsers are rejected by the
# org's iam.allowedPolicyMemberDomains policy and are the wrong posture anyway.
