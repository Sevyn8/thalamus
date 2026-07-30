###############################################################################
# cloud-run-service-streaming-consumer: the DIS streaming-consumer on the
# Thalamus data plane.
#
# A long-running Pub/Sub PULL consumer deployed as an always-on Cloud Run
# Service: RUN_HEALTH_SERVER=true serves /healthz for the Cloud Run probe while
# subscriber.run_forever() pulls ingress.ready in a sibling task. It dual-writes
# canonical rows (hot + event) plus quarantine to the DB and PUBLISHES NOTHING
# (terminal DB writer). NOT a push subscription: no OIDC push-invoker, no allUsers.
#
# Shape adapted from infra/modules/cloud-run-service-csv-ingest-worker, with:
#   1. Subscribes to ingress.ready (INGRESS_READY_SUBSCRIPTION), not csv.received.
#   2. Publishes nothing: NO pubsub.publisher grant, NO topic input.
#   3. storage.objectViewer (read-only bronze), not objectAdmin.
#   4. max_instances is a var (default 1), NOT a D58 correctness pin: the
#      consumer is concurrency-safe, so a single instance is a staging choice
#      that is safe to raise. min=1 + cpu_idle=false still required (the pull
#      loop must stay alive and CPU-allocated).
#
# NOT granted here, by design:
#   - roles/cloudsql.client: connects over the private IP at the TCP layer
#     (POSTGRES_URL host = 10.55.0.3, sslmode=require) through the VPC connector.
#     No socket/proxy is used anywhere in the consumer.
#   - Artifact Registry reader: image pulls use the Cloud Run service agent.
###############################################################################

# Dedicated runtime identity for the consumer.
resource "google_service_account" "streaming_consumer" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "DIS streaming-consumer Cloud Run runtime SA"
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
  member    = "serviceAccount:${google_service_account.streaming_consumer.email}"
}

# Read-only bronze: the consumer reads the object referenced by the ingress.ready
# event and cross-checks the bucket. It never writes GCS (canonical writes go to
# the DB), so objectViewer, not objectAdmin.
resource "google_storage_bucket_iam_member" "bronze_object_viewer" {
  bucket = var.bronze_bucket_name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${google_service_account.streaming_consumer.email}"
}

resource "google_pubsub_subscription_iam_member" "ingress_subscriber" {
  project      = var.project_id
  subscription = var.subscription_id
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.streaming_consumer.email}"
}

# pubsub.viewer at project level: the consumer's startup _require_subscription
# preflight (clients/pubsub.py) calls subscriptions.get, which is in
# roles/pubsub.viewer and is not covered by pubsub.subscriber. Without it the
# consumer errors at startup.
resource "google_project_iam_member" "pubsub_viewer" {
  project = var.project_id
  role    = "roles/pubsub.viewer"
  member  = "serviceAccount:${google_service_account.streaming_consumer.email}"
}

locals {
  # Plain env. Names are the EXACT vars streaming-consumer config.py reads.
  # REQUIRED at boot: PUBSUB_PROJECT_ID, GCS_BUCKET_BRONZE (POSTGRES_URL is
  # secret env; PORT is Cloud-Run-injected when RUN_HEALTH_SERVER is on).
  # DIS_EXPECTED_DATABASE is the dis-rls guard for the canonical dual-write path.
  # The consumer does not publish, so there is no INGRESS_READY_TOPIC.
  plain_env = {
    DIS_EXPECTED_DATABASE      = var.dis_expected_database      # parameterized dis-rls guard
    PUBSUB_PROJECT_ID          = var.project_id                 # config.py:44 required at boot
    GCS_BUCKET_BRONZE          = var.bronze_bucket_name         # config.py:45 required at boot (read-only)
    RUN_HEALTH_SERVER          = "true"                         # Cloud Run Service mode: serve /healthz
    INGRESS_READY_SUBSCRIPTION = var.ingress_ready_subscription # config.py:59 the pull subscription
  }
}

resource "google_cloud_run_v2_service" "streaming_consumer" {
  # Staging: allow teardown.
  deletion_protection = false

  project  = var.project_id
  name     = var.service_name
  location = var.region

  # Ingress ALL = the URL is reachable at the network layer (for the /healthz
  # probe). This does NOT make the service public: no invoker IAM is bound, and
  # the consumer's real work is an outbound pull loop, not inbound requests.
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
    service_account = google_service_account.streaming_consumer.email

    # min=1 always-on (pull loop must stay alive). max default 1 is a staging
    # choice, NOT a correctness pin: the consumer is concurrency-safe.
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

      # The consumer's /healthz server binds the Cloud-Run-injected $PORT (8080).
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
        name = "POSTGRES_URL" # config.py:43 required at boot; secret-backed
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
    google_storage_bucket_iam_member.bronze_object_viewer,
    google_pubsub_subscription_iam_member.ingress_subscriber,
    google_project_iam_member.pubsub_viewer,
  ]
}

# No invoker IAM binding here, and none is needed: the consumer's real work is an
# outbound pull loop, so nothing calls it inbound except the Cloud Run health probe.
# Verified live - this service has NO invoker bindings at all, so the private
# posture the rest of this comment describes is real.
#
# What was struck: the previous wording credited the org's
# iam.allowedPolicyMemberDomains policy with rejecting allUsers /
# allAuthenticatedUsers. That is false - the policy is listPolicy allValues=ALLOW on
# this project, directly and effectively, so it rejects nothing. This service is
# private because no binding was ever added, NOT because anything prevents one. The
# two HTTP services in this tree (cm-backend, dis-ui-server) are public precisely
# because that grant was made out of band with nothing standing in the way.
