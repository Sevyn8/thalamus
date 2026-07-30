###############################################################################
# cloud-run-service-cm-frontend: the CM frontend (cm-frontend) Cloud Run v2
# service on the Thalamus data plane.
#
# THIS MODULE DESCRIBES A SERVICE THAT ALREADY EXISTS. It was written to match
# the LIVE configuration field-for-field and adopted by `terraform import`, not
# by creating anything. Every value below was read from the Cloud Run v2 REST API
# (NOT `gcloud run services describe --format=export`, which returns the Knative
# v1 shape and silently omits v2-only fields such as service-level scaling). The
# acceptance test for this module is `terraform plan` reporting no changes.
#
# Shape adapted from infra/modules/cloud-run-service-cm with five deliberate
# divergences, all of them RECORDED FACTS about the live service rather than
# choices made here:
#   1. It runs as the DEFAULT COMPUTE SA, not a dedicated one. This module
#      therefore creates NO service account and asserts the default compute
#      identity. That is a finding, not an endorsement: every Terraform-managed
#      service in this tree has a dedicated SA, and this one holds
#      secretAccessor on both cm-frontend-* secrets. It is on the ledger to fix
#      before production. Changing it is a live-config change and is deliberately
#      out of this slice.
#   2. No VPC connector. The frontend talks to cm-backend over public HTTPS
#      (API_BASE_URL), never to Cloud SQL, so it needs no private egress.
#   3. A PUBLIC invoker binding exists and is declared below. Unlike cm-backend
#      and dis-ui-server (both authenticated-only in their modules' comments),
#      this service really is reachable by allUsers. See the binding's own
#      comment.
#   4. `client` / `client_version` are declared. The service was created by
#      `gcloud run deploy`, so the API reports client="gcloud". Both attributes
#      are Optional and NOT Computed in provider 6.50.0, so an undeclared value
#      is a permanent diff - the same mechanism as the service-level scaling
#      block below. Declared here BEFORE it bites rather than after.
#   5. A TCP startup probe on the app port, not cm-backend's HTTP /health probe.
#      Next.js exposes no health endpoint; the live probe is tcpSocket.
#
# NOT granted here, by design:
#   - No service account is created, so no runtime IAM is granted. The secret
#     accessor grants on cm-frontend-auth0-client-secret and
#     cm-frontend-auth0-secret are held by the default compute SA and were made
#     out of band; this module does not manage them. Importing the service does
#     not import those grants, and this slice deliberately does not touch IAM
#     beyond declaring the invoker binding that is already live.
#   - Artifact Registry reader: image pulls use the Cloud Run service agent
#     (service-<num>@serverless-robot-prod...), not the runtime identity.
###############################################################################

# Existing secrets (created out-of-band). The data sources resolve the secret
# ids for the env refs below and fail the plan fast if a secret is missing.
data "google_secret_manager_secret" "auth0_client_secret" {
  project   = var.project_id
  secret_id = var.secret_auth0_client_secret
}

data "google_secret_manager_secret" "auth0_secret" {
  project   = var.project_id
  secret_id = var.secret_auth0_secret
}

resource "google_cloud_run_v2_service" "cm_frontend" {
  # Staging: allow teardown. The live service reports no deletionProtection,
  # while the provider's own default is true - declared so the two agree.
  deletion_protection = false

  project  = var.project_id
  name     = var.service_name
  location = var.region

  # Created by `gcloud run deploy`, so the API reports these. Optional and NOT
  # Computed in the provider, so leaving them out diffs on every plan forever.
  # Do not "clean these up" - they are a record of how the service was made.
  client         = var.client
  client_version = var.client_version

  # Ingress ALL = the URL is reachable at the network layer. For THIS service
  # that also means publicly callable, because the allUsers invoker binding
  # below is live (see its comment).
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
    # The DEFAULT COMPUTE SA (divergence 1). Not a dedicated identity; this
    # module asserts what is live and creates nothing.
    service_account = var.service_account_email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    timeout                          = var.timeout
    max_instance_request_concurrency = var.max_concurrency

    containers {
      image = var.image

      # Next.js listens on 3000 (not Cloud Run's default 8080).
      ports {
        container_port = 3000
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        cpu_idle          = true
        startup_cpu_boost = true
      }

      # Plain env, declared as static blocks in the LIVE ORDER. `env` is a list
      # in the provider schema, so it diffs positionally - a dynamic block over a
      # map would emit lexical order and diff against the live ordering.
      env {
        name  = "AUTH0_DOMAIN"
        value = var.auth0_domain
      }
      env {
        name  = "AUTH0_CLIENT_ID"
        value = var.auth0_client_id
      }
      env {
        name  = "AUTH0_AUDIENCE"
        value = var.auth0_audience
      }
      env {
        name  = "API_BASE_URL"
        value = var.api_base_url
      }
      env {
        name  = "APP_BASE_URL"
        value = var.app_base_url
      }

      # Secret env vars (VALUES by reference only, never inline).
      env {
        name = "AUTH0_CLIENT_SECRET"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.auth0_client_secret.secret_id
            version = "latest"
          }
        }
      }
      env {
        name = "AUTH0_SECRET"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.auth0_secret.secret_id
            version = "latest"
          }
        }
      }

      # TCP probe, not HTTP: Next.js exposes no health path. The live values are
      # a single 240s attempt, i.e. a very wide cold-start budget rather than a
      # tight readiness gate. Recorded as-is; tuning it is a live-config change.
      startup_probe {
        tcp_socket {
          port = 3000
        }
        timeout_seconds   = 240
        period_seconds    = 240
        failure_threshold = 1
      }

      # No liveness_probe: the live service has none.
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }
}

# PUBLIC invoker binding, declared because it is LIVE - allUsers holds
# roles/run.invoker on this service today. Stated plainly rather than
# aspirationally: cm-frontend IS publicly callable at the IAM layer, and the
# app's own Auth0 session gating is what protects it. This is the first invoker
# binding in this tree; cm-backend and dis-ui-server both carry
# "authenticated-only" comments instead (dis-ui-server's is contradicted by its
# own live policy - see the ledger; not this slice's business).
#
# A module for a public service that omitted this binding would be incomplete and
# would drift on the first plan, so it is declared and imported alongside the
# service.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.cm_frontend.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
