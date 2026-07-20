###############################################################################
# artifact-registry: one Docker repository for Thalamus service images
# (cm-backend now; DIS services in Wave 3, all under the same repo).
###############################################################################

resource "google_artifact_registry_repository" "this" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  format        = "DOCKER"
  description   = "Thalamus service container images (staging)."
}
