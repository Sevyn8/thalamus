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

variable "cleanup_policy_dry_run" {
  type        = bool
  description = "Repository-wide kill switch for the cleanup policies. TRUE means the policies are attached and evaluated but NOTHING is deleted. Ships true so the config can land and be verified before any deletion happens; flip to false only after the would-delete set has been enumerated and reviewed."
  default     = true
}

variable "untagged_grace_period" {
  type        = string
  description = "How old an UNTAGGED version must be before the delete policy collects it. 90 days deliberately, not 30: orphaned digests cost pennies, so the policy's job is to bound growth rather than minimise storage, and this is the first delete policy aimed at the repository every terraform pin depends on. Duration suffixes are s/m/h/d."
  default     = "90d"
}
