variable "project_id" { type = string }
variable "region" { type = string }

variable "image" {
  type        = string
  description = <<-EOT
    THE SAME IMAGE AS THE ORCHESTRATOR, and it must stay that way. Pass
    var.synapse_orchestrator_image, never a separately pinned tag: a migration has to run the
    code it ships with, and a second pin lets the migration sit a revision behind the workload
    it migrates for. This is migrate-cm's D6 argument applied to the second chain.

    The image's CMD/ENTRYPOINT starts the orchestrator sweep; this job OVERRIDES it with
    command = ["alembic"]. Removing that override turns this into a job that runs a SWEEP
    against the database it was meant to migrate.
  EOT
}

variable "job_name" {
  type    = string
  default = "migrate-synapse"
}

variable "vpc_connector_id" {
  type        = string
  description = "Cloud SQL is private IP only; the migration reaches it over the connector at the TCP layer, exactly as the orchestrator does."
}

variable "secret_admin_url" {
  type        = string
  description = <<-EOT
    Secret Manager id of the SYNAPSE_ADMIN_URL DSN. Created OUT OF BAND, as every other DSN
    secret in this project was — Terraform only ever READS them.

    THE ROLE IS NOT YET DETERMINED. env.py names no user; it takes whatever the DSN says. The
    chain does CREATE SCHEMA, ALTER DEFAULT PRIVILEGES and GRANT, so it needs an owner-capable
    role, and sql/03:22 records the sibling convention as `postgres`. But which role actually
    ran 0001-0003 is UNKNOWN from this repository, and creating this secret against the wrong
    one would leave 0004's columns owned differently from the table they sit on. Settle it with
    `SELECT tableowner FROM pg_tables WHERE schemaname='synapse'` before creating the secret.
  EOT
  default     = "synapse-admin-database-url"
}

variable "max_retries" {
  type        = number
  description = "0: a migration that fails must be looked at, not retried. Alembic runs each revision in a transaction, so a failure leaves the version unchanged and a blind retry would just fail again against the same cause."
  default     = 0
}

variable "task_timeout" {
  type    = string
  default = "600s"
}

variable "cpu" {
  type    = string
  default = "1"
}

variable "memory" {
  type    = string
  default = "512Mi"
}

variable "client" {
  type    = string
  default = "terraform"
}

variable "client_version" {
  type    = string
  default = ""
}
