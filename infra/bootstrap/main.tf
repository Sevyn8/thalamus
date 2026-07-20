###############################################################################
# Thalamus staging: bootstrap (Wave 0).
#
# Job of this layer, and ONLY this: create the GCP project, link billing, and
# enable the baseline platform APIs. It does NOT create the Terraform state
# bucket (sevyn8-tfstate already exists, org-shared) and does NOT create any
# VPC, Postgres, secret, or service. Those land in Waves 1-4 under envs/staging.
#
# LOCAL state, by deliberate design (chicken-and-egg): this is the layer that
# stands up the project the remote-state bucket's later consumers live in, and
# it must be runnable before any remote-state wiring. There is no backend block
# here; terraform keeps state in ./terraform.tfstate (gitignored). Keep it that
# way: do not add a gcs backend to the bootstrap.
#
# Precedent: infra/_import/cm-infra/terraform/bootstrap/ (CM's bootstrap). This
# differs from CM's in two ways: (1) it CREATES the project + billing (CM's ran
# against an already-created project), and (2) it does NOT create a state bucket
# (ours pre-exists).
###############################################################################

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

# No project default: the project does not exist until this apply creates it.
# Each resource sets its own project explicitly. Credentials come from the
# operator's gcloud ADC (amit@sevyn8.com), which must hold, on org 395217984150:
# resourcemanager.projects.create and billing.resourceAssociations.create.
provider "google" {
  region = var.region
}

# The project itself, created under the sevyn8.com org with billing linked at
# create time. deletion_policy PREVENT (the v6 default, stated explicitly) so a
# stray `terraform destroy` cannot delete the project.
resource "google_project" "thalamus" {
  name            = var.project_name
  project_id      = var.project_id
  org_id          = var.org_id
  billing_account = var.billing_account
  deletion_policy = "PREVENT"
}

# Baseline platform APIs. This is DIS's project-services set (verified from
# ~/projects/ithina-retail-dis/terraform/modules/project-services/main.tf), plus
# cloudresourcemanager + serviceusage which are needed for Terraform to manage
# projects and services at all. disable_on_destroy=false so tearing down this
# config never disables live APIs.
resource "google_project_service" "baseline" {
  for_each = toset([
    # Bootstrap-necessary (Terraform manages projects/services through these).
    "cloudresourcemanager.googleapis.com",
    "serviceusage.googleapis.com",
    # Platform set (parity with DIS's project-services).
    "compute.googleapis.com",
    "servicenetworking.googleapis.com",
    "sqladmin.googleapis.com",
    "run.googleapis.com",
    "pubsub.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "vpcaccess.googleapis.com",
  ])

  project            = google_project.thalamus.project_id
  service            = each.key
  disable_on_destroy = false

  # Ordering: the project (and its billing link) must exist before any API is
  # enabled. If a service-enable races project/billing propagation on the very
  # first apply, re-running apply is safe and idempotent.
  depends_on = [google_project.thalamus]
}

output "project_id" {
  value       = google_project.thalamus.project_id
  description = "The created project id. Confirm it matches envs/staging var.project_id."
}

output "project_number" {
  value       = google_project.thalamus.number
  description = "The created project number (used later for service-agent member strings)."
}

output "state_backend_reminder" {
  value = "State bucket sevyn8-tfstate (pre-existing, org-shared) is NOT managed here. envs/staging/backend.tf points at it with prefix thalamus/staging."
}
