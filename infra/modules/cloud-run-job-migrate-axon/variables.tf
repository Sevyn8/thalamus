variable "project_id" { type = string }
variable "region" { type = string }

variable "image" {
  type        = string
  description = <<-EOT
    THE SAME IMAGE AS synapse-ui-server, and it must stay that way. Pass
    var.synapse_ui_server_image, never a separately pinned tag: a migration has to run the code
    it ships with, and a second pin lets the migration sit a revision behind the workload it
    migrates for. This is migrate-cm's D6 argument applied to the third chain.

    WHY THE BFF'S IMAGE AND NOT AN AXON IMAGE. Axon has no image of its own, because slice 1
    gives it no server: its only producer is the BFF and the send is in-process. The BFF's
    Dockerfile therefore COPYs the whole axon/ directory, chain and DDL included, and this job
    runs alembic out of it. If Axon ever gains a service of its own, this variable moves to
    that image and the reasoning above is unchanged.

    The image's CMD starts uvicorn; this job OVERRIDES it with command = ["alembic"]. Removing
    that override turns this into a job that starts a web server and hangs until its timeout,
    which is migrate-cm's recorded failure mode rather than a hypothetical one.
  EOT
}

variable "job_name" {
  type    = string
  default = "migrate-axon"
}

variable "vpc_connector_id" {
  type        = string
  description = "Cloud SQL is private IP only; the migration reaches it over the connector at the TCP layer, exactly as the orchestrator does."
}

variable "secret_admin_url" {
  type        = string
  description = <<-EOT
    Secret Manager id of the AXON_ADMIN_URL DSN. Created OUT OF BAND, as every other DSN
    secret in this project was. Terraform only ever READS them.

    THE ROLE MUST BE OWNER-CAPABLE. The chain does CREATE SCHEMA and GRANT, so it needs more
    than either application role has: axon_sender holds INSERT on one table and nothing else.
    The sibling convention is `postgres` in staging and `ithina_dis_admin` locally.

    AND THE ROLE axon_sender MUST ALREADY EXIST WHEN THIS RUNS. Migration 0001 grants USAGE on
    the schema to it, so a missing role fails the migration itself rather than the grant file.
    That is 0006's recorded ordering hazard; the manual prerequisites put CREATE ROLE first for
    exactly this reason.

    THE PASSWORD MUST BE URL-SAFE OR PERCENT-ENCODED. An unencoded '@' parses as the host
    separator, so the DSN silently points somewhere else instead of failing. Learned
    empirically on 2026-08-06 and repeated here because this secret is created by hand.
  EOT
  default     = "axon-admin-database-url"
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
