###############################################################################
# Thalamus staging variables.
#
# project_id / region / zone / labels are consumed by the provider now and by
# every Wave 1-4 module later. org_id / billing_account are consumed by
# infra/bootstrap (not by resources here); they are declared for parity and
# single-source reference, and are harmless if unused this wave. state_prefix is
# documentation only (backend.tf hardcodes the literal; backend blocks cannot
# interpolate variables).
###############################################################################

variable "project_id" {
  type        = string
  description = "GCP project id for Thalamus staging. Never ithina-dis-cm."
  default     = "sevyn8-thalamus-staging"
}

variable "region" {
  type        = string
  description = "Primary region for all Thalamus staging resources."
  default     = "asia-south1"
}

variable "zone" {
  type        = string
  description = "Zone for zonal resources (later waves)."
  default     = "asia-south1-c"
}

variable "org_id" {
  type        = string
  description = "GCP organization id (sevyn8.com). Reference only here; consumed by infra/bootstrap."
  default     = "395217984150"
}

variable "billing_account" {
  type        = string
  description = "Billing account id. Reference only here; consumed by infra/bootstrap."
  default     = "016691-555E7E-B5AB24"
}

variable "state_prefix" {
  type        = string
  description = "Documentation of the remote-state prefix. backend.tf hardcodes this literal (backend blocks cannot use variables)."
  default     = "thalamus/staging"
}

variable "labels" {
  type        = map(string)
  description = "Default labels applied to every resource that supports labels."
  default = {
    workload    = "thalamus"
    env         = "staging"
    cost_center = "sevyn8"
  }
}
