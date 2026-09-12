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
#   1. Its runtime identity is created OUTSIDE this module, at the staging root,
#      and passed in as var.service_account_email. Every other service in this
#      tree creates its own; this one cannot, because Synapse's invoker binding
#      must name the same account while cm-frontend already depends on Synapse,
#      and owning the account here would close that into a graph cycle. The
#      variable has no default, so there is no path back to the shared identity
#      by omission. (P1-IAM-001A. Before it, this ran as the project's DEFAULT
#      COMPUTE SA - the shared identity dis-ui-ver2 also used, which meant
#      Synapse's invoker binding admitted every default-compute workload in the
#      project rather than this service.)
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
# GRANTED here, and nothing more (P1-IAM-001A):
#   - roles/secretmanager.secretAccessor on cm-frontend-auth0-client-secret and
#     cm-frontend-auth0-secret, secret-scoped. See the resources below.
#   The Synapse roles/run.invoker grant this identity also holds lives in
#   cloud-run-service-synapse-ui-server, next to the service it admits access to.
#
# NOT granted here, by design:
#   - Nothing project-wide. No project-level secretAccessor, no project-level
#     run.invoker, no Editor/Viewer.
#   - No service account key. Cloud Run attaches the identity to the revision and
#     the metadata server mints tokens; a key would be a downloadable long-lived
#     credential for a workload that cannot use one.
#   - Nothing for the ID token it mints against SYNAPSE_BFF_URL. Asking the
#     metadata server for an identity token is not an IAM-gated action on the
#     caller side - the token is only useful where the AUDIENCE service has
#     granted this identity invoker, which is precisely the Synapse binding.
#   - Artifact Registry reader: image pulls use the Cloud Run service agent
#     (service-<num>@serverless-robot-prod...), not the runtime identity.
#
# WHAT TERRAFORM DOES NOT OWN HERE, AND WHY THAT MATTERS TO A READER CHECKING
# THIS FILE AGAINST THE LIVE POLICY. Both secrets were created OUT OF BAND,
# before this repository described the service, and so were the project default
# compute SA's historical secretAccessor grants on them. Terraform has never
# managed those members: it manages exactly the two dedicated cm-frontend-sa
# members declared below and nothing else on either policy.
#
# THIS FILE CANNOT TELL YOU WHETHER THE HISTORICAL MEMBERS STILL EXIST. Removing
# them is the closing step of P1-IAM-001B and is performed as an explicit live
# IAM operation (`gcloud secrets remove-iam-policy-binding` against the named
# member), not by anything in this configuration. No code change here records
# it, `terraform plan` does not observe it, and no assertion in this repository
# can establish it. THE LIVE IAM POLICY IS THE ONLY AUTHORITY ON THAT FACT --
# read it with `gcloud secrets get-iam-policy` rather than inferring it from
# this file in either direction.
#
# CONSEQUENCE: the member list on either secret may legitimately be longer than
# what this module declares. That is a property of additive IAM, not drift.
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

# Least-privilege: the dedicated runtime SA gets secretAccessor on exactly these
# two secrets, at the SECRET level. No project-wide grant - a project-level
# secretAccessor would hand this identity every credential in the estate,
# including cm-backend's DSN and the per-tenant channel vault.
#
# ADDITIVE (`_iam_member`), NOT AUTHORITATIVE (`_iam_binding`), AND IT STAYS THAT
# WAY, because Terraform does not own these policies. An `_iam_binding` computes
# the complete member list from this file alone and deletes everyone it does not
# find here -- on secrets created out of band, that means silently asserting
# ownership of members this repository has never seen.
#
# THE COST WAS CONCRETE DURING THE P1-IAM-001A CUTOVER, and is worth keeping as
# the worked example: the project default compute SA held the same role on both
# secrets and the then-serving revision read them with it, so an authoritative
# binding would have deleted that grant on apply and blacked out the live service
# before its replacement revision existed. The reasoning is not specific to that
# member or to that migration; it follows from who owns the policy.
resource "google_secret_manager_secret_iam_member" "auth0_client_secret" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.auth0_client_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
}

resource "google_secret_manager_secret_iam_member" "auth0_secret" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.auth0_secret.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${var.service_account_email}"
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
    # The dedicated runtime identity (divergence 1), created at the root and
    # passed in. Changing this field rolls a revision, which is the entire
    # mechanism of the P1-IAM-001A cutover: the new revision's metadata server
    # starts minting ID tokens for THIS account, so Synapse begins seeing
    # cm-frontend-sa as the caller rather than the shared default-compute one.
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
      # Read only by Next.js SERVER components (lib/synapse/server-client.ts).
      # Non-prefixed and therefore never inlined into the client bundle, which is
      # the point: the browser must not learn this origin, because the browser is
      # not permitted to call it.
      env {
        name  = "SYNAPSE_BFF_URL"
        value = var.synapse_bff_url
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

  # THE GRANTS MUST EXIST BEFORE THE REVISION THAT READS THEM, AND NOTHING ELSE
  # IN THIS FILE SAYS SO. The env blocks above reference
  # `data.google_secret_manager_secret.*.secret_id` - the DATA SOURCE. Terraform
  # sees an edge to the data source and NO EDGE AT ALL to the secret_iam_member
  # resources, so without this list it is free to roll the revision onto the new
  # identity before that identity can read either secret. The container then
  # starts without AUTH0_CLIENT_SECRET/AUTH0_SECRET, the apply is green, and the
  # plan says nothing. Same failure this estate already paid for on
  # synapse-ui-server; `test_every_secret_iam_member_is_listed_in_the_services_depends_on`
  # in cm-backend/tests/unit/test_frontend_runtime_identities.py is what keeps a
  # future third secret from being added without its edge.
  depends_on = [
    google_secret_manager_secret_iam_member.auth0_client_secret,
    google_secret_manager_secret_iam_member.auth0_secret,
  ]
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
