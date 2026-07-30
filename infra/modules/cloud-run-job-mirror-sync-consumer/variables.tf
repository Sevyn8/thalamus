###############################################################################
# cloud-run-job-mirror-sync-consumer variables.
#
# The two db_name-shaped variables below default to `thalamus` DELIBERATELY, which
# is the opposite of the code's own defaults. The service and dis-rls both default
# to pre-consolidation database names that no longer exist; inheriting either is a
# loud-but-confusing failure. Setting them here is the whole point.
#
# `image` has no default: it is pinned by the env so a build and its pin move
# together.
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
  default     = "mirror-sync-consumer"
}

variable "image" {
  type        = string
  description = "Full container image reference. NO DEFAULT: the env pins it (var.mirror_sync_consumer_image) so a build and its pin move together. Built by dis/terraform/docker/mirror-sync-consumer.Dockerfile via cloudbuild-mirror-sync-consumer.yaml with an explicit _TAG and no floating `latest`."
}

variable "service_account_id" {
  type        = string
  description = "account_id for the DEDICATED runtime service account (before the @project.iam.gserviceaccount.com suffix). Dedicated on purpose: migrate-cm reuses cm-backend-sa, but that was adopted by import rather than chosen."
  default     = "mirror-sync-consumer-sa"
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector id (module.network.vpc_connector_id / thalamus-vpcconn). BOTH database connections ride this - post-consolidation the CM read and the DIS write are the same instance."
}

# --- The two stale defaults this module exists to override ---

variable "db_name" {
  type        = string
  description = "CM_DB_NAME - the database the CM read asserts it landed on. `thalamus` for the consolidated deploy. The service's own default is ithina_platform_db, the pre-consolidation CM database, which no longer exists; inherited, the run exits 3 naming a database nobody has heard of."
  default     = "thalamus"
}

variable "dis_expected_database" {
  type        = string
  description = "DIS_EXPECTED_DATABASE - the parameterized dis-rls write guard. `thalamus` for the consolidated deploy. dis-rls's own default is ithina_dis_db, likewise gone; inherited, the write guard refuses `thalamus` and the run exits 5 before any upsert."
  default     = "thalamus"
}

# --- Secret Manager secret ids (values never enter Terraform state) ---

variable "secret_cm_read_url" {
  type        = string
  description = "Secret id holding CM_DB_URL, the Customer Master READ DSN. Connects as dis_mirror_reader (USAGE on core + SELECT on core.tenants and core.stores, nothing else). NOT cm-database-url: that DSN connects as user_admin_backend, which owns core and holds full DML - see the read-role block in main.tf."
  default     = "dis-mirror-reader-database-url"
}

variable "secret_database_url" {
  type        = string
  description = "Secret id holding POSTGRES_URL, the DIS WRITE DSN. Connects as ithina_dis_user; the same secret the DIS services consume, so the mirror write and the canonical writes agree on the target by construction."
  default     = "dis-database-url"
}

# --- gcloud/terraform provenance (see main.tf) ---

variable "client" {
  type        = string
  description = "The API's `client` field. Optional and NOT Computed in provider 6.50.0, so an undeclared value diffs on every plan forever - the 2a lesson applied before it bites. This job is terraform-created, so `terraform` is what terraform writes."
  default     = "terraform"
}

variable "client_version" {
  type        = string
  description = "The API's `client_version` field. Declared for the same reason as `client`."
  default     = "6.50.0"
}

# --- Execution shape ---

variable "task_count" {
  type        = number
  description = "Tasks per execution. Exactly 1: the sync is a single pass over all tenants, nothing about it parallelises, and two concurrent passes would race on the same identity_mirror rows."
  default     = 1
}

variable "max_retries" {
  type        = number
  description = "Retries per task. ZERO - not because a retry is dangerous (the upsert is idempotent: ON CONFLICT DO UPDATE ... WHERE IS DISTINCT FROM, so a no-change re-run is a true no-op) but because the exit code is the operator's signal and a silent retry muddies it."
  default     = 0
}

variable "task_timeout" {
  type        = string
  description = "Per-task timeout. 600s is headroom, not a tuned bound: the pass is one read of two tables plus one transaction per tenant, and there are single digits of tenants."
  default     = "600s"
}

variable "execution_environment" {
  type        = string
  description = "Cloud Run execution environment. GEN2, matching the other jobs in this tree."
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
