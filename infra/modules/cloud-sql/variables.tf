variable "project_id" {
  type        = string
  description = "GCP project id (sevyn8-thalamus-staging)."
}

variable "region" {
  type        = string
  description = "Region for the Cloud SQL instance."
}

variable "instance_name" {
  type        = string
  description = "Cloud SQL instance name."
  default     = "thalamus-pg"
}

variable "database_name" {
  type        = string
  description = "The single shared database name. Neutral (not either app's current db name); BOTH apps point DATABASE_URL here."
  default     = "thalamus"
}

variable "tier" {
  type        = string
  description = "Cloud SQL machine tier. Default db-custom-1-3840 (1 vCPU / 3.75 GB), the smallest modern ENTERPRISE tier valid for POSTGRES_16 (the legacy shared-core db-f1-micro / db-g1-small are deprecated for newer Postgres). Override down only if confirmed valid for PG16."
  default     = "db-custom-1-3840"
}

variable "disk_size_gb" {
  type        = number
  description = "Data disk size in GB (autoresize on)."
  default     = 10
}

variable "availability_type" {
  type        = string
  description = "ZONAL for staging (single zone, no HA); REGIONAL for prod."
  default     = "ZONAL"
}

variable "deletion_protection" {
  type        = bool
  description = "Prevent accidental instance destroy."
  default     = true
}

variable "environment" {
  type        = string
  description = "Environment label."
  default     = "staging"
}

variable "network_id" {
  type        = string
  description = "VPC self link/id for private IP (from the network module)."
}

variable "private_service_connection" {
  type        = string
  description = "Service Networking connection id, to enforce create ordering."
}

variable "cm_app_user_name" {
  type        = string
  description = "CM (admin-backend) application role."
  default     = "user_admin_backend"
}

variable "dis_app_user_name" {
  type        = string
  description = "DIS application role."
  default     = "ithina_dis_user"
}

variable "dis_mirror_reader_user_name" {
  type        = string
  description = "DIS cross-schema mirror-reader role (read-only on core.tenants/core.stores)."
  default     = "dis_mirror_reader"
}

variable "secret_prefix" {
  type        = string
  description = "Prefix for the Secret Manager password containers (e.g. thalamus -> thalamus-user_admin_backend-password)."
  default     = "thalamus"
}
