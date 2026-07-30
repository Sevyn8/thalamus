###############################################################################
# cloud-run-service-dis-ui-ver2: the DIS UI SPA (dis-ui-ver2) Cloud Run v2
# service on the Thalamus data plane.
#
# THIS MODULE DESCRIBES A SERVICE THAT ALREADY EXISTS. It was written to match
# the LIVE configuration field-for-field and adopted by `terraform import`, not
# by creating anything. Every value below was read from the Cloud Run v2 REST API
# (NOT `gcloud run services describe --format=export`, which returns the Knative
# v1 shape and silently omits v2-only fields such as service-level scaling). The
# acceptance test for this module is `terraform plan` reporting no changes.
#
# ==========================================================================
# THE COUPLING. READ THIS BEFORE CHANGING dis-ui-server's IAM.
# ==========================================================================
# This container is nginx serving a static Vite bundle. The SPA calls
# same-origin "/api/v1/..." and nginx reverse-proxies /api to dis-ui-server at
# ${DIS_UI_SERVER_BASE_URL}. nginx overrides only Host and the two X-Forwarded-*
# headers, so the browser's Auth0 bearer token passes straight through and
# dis-ui-server verifies it at the APPLICATION layer.
#
# nginx has NO CREDENTIAL OF ITS OWN. It attaches no Google identity, no ID
# token, no service-account auth. The proxy therefore works ONLY because
# dis-ui-server currently carries an `allUsers` roles/run.invoker binding, i.e.
# Cloud Run performs no IAM check on the inbound request and the Auth0 JWT is the
# only gate.
#
# CONSEQUENCE: the moment anyone tightens dis-ui-server's posture - removes
# allUsers, switches to authenticated-only, or fronts it with IAM - EVERY /api
# call through dis-ui-ver2 breaks IMMEDIATELY with 403. Not degraded, not slower:
# the whole UI's data layer stops, because nginx has nothing to present.
#
# This is invisible from reading either module alone. dis-ui-server's own module
# asserts twice that it is "authenticated-only (NO allUsers binding)" and cites an
# org policy as the reason, and BOTH claims are false against the live project
# (the policy is allValues:ALLOW and allUsers is bound). Slice 2b-iii is where
# that gets reconciled and is exactly where someone would trip on this. If the
# tightening is the goal, dis-ui-ver2 needs a credential first - an ID-token
# minting sidecar/proxy, or moving the /api hop server-side - and that is a
# design change, not an IAM edit.
# ==========================================================================
#
# Written as its OWN module rather than sharing one with
# cloud-run-service-cm-frontend, deliberately. The two envelopes are near
# identical (same default compute SA, same TCP probe shape, same resources, same
# allUsers invoker), and the temptation to parameterise is real - but duplicate
# at two, extract at three. ver2 also genuinely diverges: port 8080 not 3000, one
# env var not seven, and ZERO Secret Manager references, so a shared module would
# carry a secrets block that this service does not want.
#
# Divergences from cloud-run-service-cm (the module both frontends are shaped
# after), all of them RECORDED FACTS about the live service:
#   1. Runs as the DEFAULT COMPUTE SA, not a dedicated one. This module creates
#      no service account. A finding, not an endorsement: every Terraform-managed
#      service in this tree has a dedicated SA. On the ledger as HIGH (the same
#      item covers cm-frontend). Changing it rolls a revision, so it is
#      deliberately out of this slice.
#   2. No VPC connector. Traffic to dis-ui-server goes over public HTTPS.
#   3. A PUBLIC invoker binding exists and is declared below.
#   4. `client` / `client_version` are declared - the service was created by
#      `gcloud run deploy`, and both attributes are Optional and NOT Computed in
#      provider 6.50.0, so an undeclared value is a permanent diff. Same
#      mechanism as the service-level scaling block. Declared before it bites.
#   5. TCP startup probe, not cm-backend's HTTP /health probe. nginx serves the
#      SPA; there is no health endpoint.
#   6. No secrets at all. The single env var is a plain URL.
#
# NOT granted here, by design:
#   - No service account is created, so no runtime IAM is granted.
#   - Artifact Registry reader: image pulls use the Cloud Run service agent
#     (service-<num>@serverless-robot-prod...), not the runtime identity.
###############################################################################

resource "google_cloud_run_v2_service" "dis_ui_ver2" {
  # Staging: allow teardown. The live service reports no deletionProtection,
  # while the provider's own default is true - declared so the two agree. This is
  # a terraform-state guard, not an API field.
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

      # nginx listens on 8080 (the Dockerfile's EXPOSE and the nginx template's
      # `listen 8080`), which is also Cloud Run's default port.
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

      # The ONLY env var, and it is RUNTIME not build-time. The SPA's Vite vars
      # are baked into the static bundle at `vite build` (see
      # dis/terraform/docker/dis-ui-ver2.Dockerfile); this one is read at
      # container start by envsubst-on-templates, which rewrites
      # ${DIS_UI_SERVER_BASE_URL} into the nginx config before nginx boots. A
      # /docker-entrypoint.d/15- script fails the container loudly if it is
      # unset, so an empty value is a crash-on-boot, not a silent misroute.
      #
      # This is the value the coupling comment at the top of this file is about.
      env {
        name  = "DIS_UI_SERVER_BASE_URL"
        value = var.dis_ui_server_base_url
      }

      # TCP probe, not HTTP: nginx serves a static bundle with no health path.
      # The live values are a single 240s attempt, i.e. a very wide cold-start
      # budget rather than a tight readiness gate. Recorded as-is; tuning it is a
      # live-config change and belongs in its own commit.
      startup_probe {
        tcp_socket {
          port = 8080
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
# aspirationally: dis-ui-ver2 IS publicly callable at the IAM layer, and the SPA's
# own Auth0 session is what gates access to data.
#
# Note the asymmetry with the coupling comment above: removing THIS binding breaks
# users' access to the UI. Removing dis-ui-server's binding breaks the UI's /api
# calls while leaving the page loading. The second failure is the confusing one.
resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.dis_ui_ver2.name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
