###############################################################################
# cloud-run-job-migrate-cm variables.
#
# Every default below is the value READ FROM THE LIVE JOB via the Cloud Run v2
# REST API, because this module exists to describe a job that already exists. A
# default that disagrees with live shows up as a plan diff, which is what this
# module is verified against.
#
# `image` and `service_account_email` have NO defaults on purpose: both are owned
# elsewhere (var.cm_image and the cloud-run-service-cm module's SA output) and a
# default here would be a second source of truth that could drift.
###############################################################################

variable "project_id" {
  type        = string
  description = "GCP project id. Thalamus staging is sevyn8-thalamus-staging; never ithina-dis-cm."
}

variable "region" {
  type        = string
  description = "Region for the Cloud Run job (asia-south1 for Thalamus staging)."
}

variable "job_name" {
  type        = string
  description = "Cloud Run v2 job name."
  default     = "migrate-cm"
}

variable "image" {
  type        = string
  description = "Full container image reference. NO DEFAULT: this MUST be the same image as the cm-backend service (D6), so the env passes var.cm_image. A default here would be a second pin that could drift from the service it migrates for."
}

variable "service_account_email" {
  type        = string
  description = "Runtime identity. NO DEFAULT: the env passes module.cm_service.service_account_email (cm-backend-sa), which the cloud-run-service-cm module owns and which already holds secretAccessor on cm-database-url. Passing it in orders the SA before the job and keeps one source of truth."
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector id (module.network.vpc_connector_id / thalamus-vpcconn). Egress to the private Cloud SQL IP goes through this."
}

# --- gcloud provenance (see main.tf divergence 4) ---

variable "client" {
  type        = string
  description = "The API's `client` field. 'gcloud' because the job was created with the gcloud CLI. Optional and NOT Computed in the provider, so it must be declared or every plan diffs."
  default     = "gcloud"
}

variable "client_version" {
  type        = string
  description = "The API's `client_version` field, set by whichever gcloud created/last-updated the job. Declared for the same reason as `client`."
  default     = "569.0.0"
}

# --- Execution shape ---

variable "task_count" {
  type        = number
  description = "Tasks per execution. Exactly 1: `alembic upgrade head` is not parallelisable - two concurrent runs race on the alembic_version row."
  default     = 1
}

variable "max_retries" {
  type        = number
  description = "Retries per task. ZERO deliberately: a failed migration must stay failed and visible, because a silent retry runs against a schema the first attempt already moved."
  default     = 0
}

variable "task_timeout" {
  type        = string
  description = "Per-task timeout. 600s is the live value; recent executions complete in ~21s, so this is headroom rather than a tuned bound."
  default     = "600s"
}

variable "execution_environment" {
  type        = string
  description = "Cloud Run execution environment. GEN2 matches the live job."
  default     = "EXECUTION_ENVIRONMENT_GEN2"
}

variable "cpu" {
  type        = string
  description = "Container CPU limit."
  default     = "1000m"
}

variable "memory" {
  type        = string
  description = "Container memory limit."
  default     = "512Mi"
}

# --- CM wiring ---

variable "db_schema" {
  type        = string
  description = "DB_SCHEMA - the Postgres schema Alembic targets. Parameterised per environment by CM's own design; `core` on staging."
  default     = "core"
}

variable "secret_database_url" {
  type        = string
  description = "Secret id holding DATABASE_URL. The SAME secret the cm-backend service consumes, so the migration and the app agree on the target database by construction."
  default     = "cm-database-url"
}
