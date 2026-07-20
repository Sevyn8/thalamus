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

###############################################################################
# Wave 1: network
###############################################################################

variable "name_prefix" {
  type        = string
  description = "Prefix for shared network resource names."
  default     = "thalamus"
}

variable "subnet_cidr" {
  type        = string
  description = "Primary subnet CIDR for the shared VPC."
  default     = "10.20.0.0/24"
}

variable "connector_cidr" {
  type        = string
  description = "The /28 for the Serverless VPC Access connector (must not overlap subnet_cidr)."
  default     = "10.8.0.0/28"
}

###############################################################################
# Wave 1: Cloud SQL (shared instance + shared database + three roles)
###############################################################################

variable "cloud_sql_instance_name" {
  type        = string
  description = "Cloud SQL instance name."
  default     = "thalamus-pg"
}

variable "database_name" {
  type        = string
  description = "The single shared database name. Neutral; BOTH apps point DATABASE_URL here."
  default     = "thalamus"
}

variable "cloud_sql_tier" {
  type        = string
  description = "Cloud SQL machine tier. See modules/cloud-sql for the default rationale (db-custom-1-3840, smallest modern ENTERPRISE tier for POSTGRES_16)."
  default     = "db-custom-1-3840"
}

variable "cloud_sql_disk_size_gb" {
  type        = number
  description = "Cloud SQL data disk size in GB."
  default     = 10
}

variable "cloud_sql_availability_type" {
  type        = string
  description = "ZONAL for staging; REGIONAL for prod."
  default     = "ZONAL"
}

variable "cloud_sql_deletion_protection" {
  type        = bool
  description = "Prevent accidental instance destroy."
  default     = true
}
