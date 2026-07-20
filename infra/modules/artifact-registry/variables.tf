variable "project_id" {
  type        = string
  description = "GCP project id (sevyn8-thalamus-staging)."
}

variable "region" {
  type        = string
  description = "Region for the Artifact Registry repository."
}

variable "repository_id" {
  type        = string
  description = "Docker repository id. Images push to <region>-docker.pkg.dev/<project>/<repository_id>/<image>."
  default     = "thalamus-images"
}
