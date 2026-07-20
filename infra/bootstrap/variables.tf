variable "project_id" {
  type        = string
  description = "Globally-unique GCP project id to create. Thalamus staging: sevyn8-thalamus-staging."
}

variable "project_name" {
  type        = string
  description = "Human-readable project display name."
  default     = "Thalamus Staging"
}

variable "org_id" {
  type        = string
  description = "GCP organization id to create the project under (sevyn8.com = 395217984150)."
}

variable "billing_account" {
  type        = string
  description = "Billing account id to link (format XXXXXX-XXXXXX-XXXXXX)."
}

variable "region" {
  type        = string
  description = "Default provider region."
  default     = "asia-south1"
}
