###############################################################################
# synapse-ui-server: the read-only BFF behind Synapse's superadmin console.
#
# Called SERVER-SIDE by cm-frontend's Next.js server components. The browser
# never reaches it, so it needs no public invoker binding and no CORS.
#
# READ-ONLY, AND THE CREDENTIAL SAYS SO. It is given the synapse_reader DSN and
# nothing else — no writer secret is granted, no writer env var is set, and the
# service refuses to START if SYNAPSE_WRITER_URL is present. Slice 8b needs a
# writer for provisioning and must add it deliberately rather than find it
# already wired.
#
# ==========================================================================
# THE INVOKER BINDING: WHAT IT ACHIEVES, AND WHAT IT DOES NOT
# ==========================================================================
# Three facts, and the third is the one that would otherwise be misread:
#
#   1. THIS BINDING REMOVES ANONYMOUS ACCESS. That is the substance of the
#      standing HIGH ledger finding — every other HTTP service in this project
#      (cm-backend, cm-frontend, dis-ui-server, dis-ui-ver2) carries an
#      `allUsers` invoker binding with the JWT as the sole gate. This service
#      does not. It is the first one, which makes fixing the others a precedent
#      rather than a proposal.
#
#   2. IT DOES NOT RESTRICT THE CALLER TO cm-frontend. cm-frontend has NO
#      DEDICATED SERVICE ACCOUNT — it runs as the project's DEFAULT COMPUTE
#      identity, recorded as a ledger item in
#      infra/modules/cloud-run-service-cm-frontend/main.tf. dis-ui-ver2 runs as
#      the same identity.
#
#   3. SO ANY WORKLOAD RUNNING AS DEFAULT COMPUTE IN THIS PROJECT CAN INVOKE
#      THIS SERVICE, and "restricted to cm-frontend" would be a FALSE STATEMENT.
#      It is not written anywhere in this module for that reason.
#
# The real fix is giving cm-frontend a dedicated service account, which closes
# the ledger item and makes the member below mean what it appears to mean. That
# is ITS OWN SLICE WITH A WINDOW, not a side effect of a UI build: the two
# cm-frontend-* Auth0 secretAccessor grants were made OUT OF BAND, so a new
# service account must have them re-granted before the frontend can boot. Doing
# it silently here would risk an outage on a running frontend to improve a
# comment.
#
# NOT granted here, by design:
#   - No secretAccessor on any writer DSN. There is no write path to serve.
#   - No roles/cloudsql.client: Cloud SQL is reached over the private IP through
#     the VPC connector, at the TCP layer, as the orchestrator does.
#   - No Artifact Registry reader: image pulls use the Cloud Run service agent.
###############################################################################

# A DEDICATED runtime identity, unlike cm-frontend's. Every Terraform-managed
# service in this tree has one; the frontend's absence of one is the exception
# and the thing point 2 above is about.
resource "google_service_account" "synapse_ui_server" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "Synapse UI server (read-only BFF) runtime SA"
}

# The reader DSN, created out of band. The data source fails the PLAN if it is
# missing, which is the right time to find out.
data "google_secret_manager_secret" "reader_url" {
  project   = var.project_id
  secret_id = var.secret_reader_url
}

resource "google_secret_manager_secret_iam_member" "reader_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.reader_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.synapse_ui_server.email}"
}

resource "google_cloud_run_v2_service" "synapse_ui_server" {
  deletion_protection = false

  project  = var.project_id
  name     = var.service_name
  location = var.region
  # INTERNAL ingress: reachable from inside the VPC and from other Cloud Run
  # services in the project, not from the internet. This is the second half of
  # the posture — IAM says who may invoke, ingress says from where.
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  client         = var.client
  client_version = var.client_version

  template {
    service_account = google_service_account.synapse_ui_server.email

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      # dis-rls refuses any database but its expected one, defaulting to the
      # pre-consolidation ithina_dis_db which no longer exists.
      env {
        name  = "DIS_EXPECTED_DATABASE"
        value = var.dis_expected_database
      }

      env {
        name  = "SYNAPSE_JWT_ISSUER"
        value = var.jwt_issuer
      }

      env {
        name  = "SYNAPSE_JWT_AUDIENCE"
        value = var.jwt_audience
      }

      # The ONLY database credential this service is given. There is deliberately
      # no SYNAPSE_WRITER_URL block; the service refuses to start if one appears.
      env {
        name = "SYNAPSE_READER_URL"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.reader_url.secret_id
            version = "latest"
          }
        }
      }
    }
  }
}

# See the header. This grants invoke to the DEFAULT COMPUTE identity because that
# is what cm-frontend runs as — which means every default-compute workload in the
# project, not cm-frontend alone.
resource "google_cloud_run_v2_service_iam_member" "frontend_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.synapse_ui_server.location
  name     = google_cloud_run_v2_service.synapse_ui_server.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.caller_service_account_email}"
}
