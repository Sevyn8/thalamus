# Provider is pinned to var.project_id (default sevyn8-thalamus-staging). It MUST NEVER
# default to ithina-dis-cm; there is no reference to that project anywhere in
# this tree.
provider "google" {
  project = var.project_id
  region  = var.region

  default_labels = var.labels
}

provider "google-beta" {
  project = var.project_id
  region  = var.region

  default_labels = var.labels
}
