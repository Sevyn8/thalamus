variable "project_id" {
  type        = string
  description = "The Thalamus GCP project id."
}

variable "region" {
  type        = string
  description = "Region for the Cloud Run job AND the Cloud Scheduler job. Both must be a region Cloud Scheduler serves; confirm with `gcloud scheduler locations list` before changing it."
  default     = "asia-south1"
}

variable "job_name" {
  type        = string
  description = "Cloud Run job name. Also the last path segment of the scheduler's :run target."
  default     = "synapse-orchestrator"
}

variable "scheduler_job_name" {
  type        = string
  description = "Cloud Scheduler job name."
  default     = "synapse-orchestrator-daily"
}

variable "image" {
  type        = string
  description = "Fully-qualified image, pinned to an explicit vN tag. NEVER :latest — a floating tag is how thalamus-images/dis-ui-ver2:latest came to point at v7 while v15 was serving. Built by synapse/cloudbuild.yaml from the MONOREPO ROOT."
}

variable "service_account_id" {
  type        = string
  description = "Account id for the job's RUNTIME identity. Holds secretAccessor on exactly the two Synapse DSN secrets and nothing else."
  default     = "synapse-orchestrator"
}

variable "scheduler_service_account_id" {
  type        = string
  description = "Account id for the identity Cloud Scheduler authenticates as. Holds roles/run.invoker on this job resource only — never project-wide."
  default     = "synapse-scheduler"
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector. The job reaches Cloud SQL over the private IP through this, which is why it needs no roles/cloudsql.client."
}

variable "dis_expected_database" {
  type        = string
  description = "The database dis-rls will accept. Must be the consolidated `thalamus`; dis-rls's own default is the pre-consolidation `ithina_dis_db`, which no longer exists, and inheriting it makes every query fail with RlsContextError before touching a row."
  default     = "thalamus"
}

variable "secret_reader_url" {
  type        = string
  description = "Secret Manager id of the synapse_reader DSN. Created out of band; Terraform only reads DSN secrets in this project."
  default     = "synapse-reader-database-url"
}

variable "secret_writer_url" {
  type        = string
  description = "Secret Manager id of the synapse_writer DSN. Created out of band (version 1, 2026-08-04)."
  default     = "synapse-writer-database-url"
}

variable "schedule" {
  type        = string
  description = "Cron, interpreted in schedule_time_zone. Default `30 21 * * *` UTC is 03:00 next day in Asia/Kolkata — after overnight ingestion and three hours clear of local midnight, which the slot residual requires. Before changing it, run the 02:00-05:00 rule query in main.tf."
  default     = "30 21 * * *"
}

variable "schedule_time_zone" {
  type        = string
  description = "Timezone the cron is read in. UTC deliberately: the tenant's zone here would put a per-customer fact in terraform, and UTC is DST-free so the fired instant never moves."
  default     = "UTC"
}

variable "attempt_deadline" {
  type        = string
  description = "How long Cloud Scheduler waits for the :run API call to be ACCEPTED. Bounds the API call, not the sweep — the job has its own task_timeout."
  default     = "320s"
}

variable "scheduler_retry_count" {
  type        = number
  description = "Zero. The job's own max_retries=1 covers the case a retry helps (a crashed sweep, adopted by takeover); a scheduler retry launches a second EXECUTION, which the slot key makes harmless but also useless. One retry mechanism, the one closest to the failure."
  default     = 0
}

variable "task_count" {
  type        = number
  description = "One. The sweep is a single pass over all provisioned pairs; there is nothing to parallelise across."
  default     = 1
}

variable "max_retries" {
  type        = number
  description = "ONE, diverging from mirror-sync's zero. A crashed sweep leaves its run row unfinished and the takeover path adopts it — with zero retries that path could only fire on the next day's dispatch, 24h later. A retry after a terminal failure re-attempts nothing (claim() skips it) and still exits non-zero, so the execution stays red."
  default     = 1
}

variable "task_timeout" {
  type        = string
  description = "Per-task wall clock. A sweep over a handful of tenants is seconds; this is a runaway bound, not a target."
  default     = "900s"
}

variable "execution_environment" {
  type        = string
  description = "Cloud Run execution environment."
  default     = "EXECUTION_ENVIRONMENT_GEN2"
}

variable "cpu" {
  type        = string
  description = "CPU limit. The work is IO-bound on Postgres, not compute-bound."
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Memory limit. The sweep holds one tenant's positions in memory at a time; 66 rows today, and the resolvers carry their own runaway guard."
  default     = "512Mi"
}

variable "client" {
  type        = string
  description = "Declared because it is Optional and NOT Computed in the provider: undeclared, it diffs on every plan forever."
  default     = "terraform"
}

variable "client_version" {
  type        = string
  description = "See `client`."
  default     = ""
}
