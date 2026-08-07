variable "project_id" { type = string }
variable "region" { type = string }

variable "image" {
  type        = string
  description = <<-EOT
    The migrate-dis image, built from dis/terraform/docker/migrate-dis.Dockerfile.

    A DEDICATED IMAGE, unlike migrate-cm (shares cm-backend's) and migrate-synapse (shares the
    orchestrator's). Both of those reuse a workload image because that workload's image already
    carried the chain. DIS's chain lives at the workspace root and no DIS service image carries
    alembic at all — measured, not assumed. The Dockerfile header carries the full argument.

    PIN AN EXPLICIT vN, never `latest`, and keep it in step with the tag built by
    dis/terraform/docker/cloudbuild-migrate-dis.yaml. For a MIGRATION image a stale pin is
    quiet in the worst way: the job runs an older chain, succeeds, and leaves the schema at a
    head nobody asked for.
  EOT
}

variable "job_name" {
  type    = string
  default = "migrate-dis"
}

variable "vpc_connector_id" {
  type        = string
  description = "Cloud SQL is private IP only; the migration reaches it over the connector at the TCP layer, exactly as the DIS workloads do."
}

variable "secret_admin_url" {
  type        = string
  description = <<-EOT
    Secret Manager id of the POSTGRES_ADMIN_URL DSN. Created OUT OF BAND, as every other DSN
    secret in this project was — Terraform only ever READS them.

    THE ROLE IS `postgres`, and unlike Synapse's equivalent this is settled rather than open.
    infra/db-setup/README.md:47 records the actual 2026-07-20 run as `postgres`, and :116
    corroborates it with the exact environment (`POSTGRES_ADMIN_URL=postgres`,
    `POSTGRES_DB=thalamus`). The same file's :32 says `ithina_dis_user`, but that is the PLAN
    line and it is stale — see the module header. Creating this against `ithina_dis_user` would
    leave new objects owned differently from the tables they sit on.

    Deliberately NOT `synapse-admin-database-url`. Two chains, two secrets, two identities:
    sharing one would let either plane's migration run with the other's credential.

    THE PASSWORD MUST BE URL-SAFE. An unencoded '@' parses as the host separator and the DSN
    silently resolves elsewhere instead of failing.
  EOT
  default     = "dis-admin-database-url"
}

variable "expected_database" {
  type        = string
  description = <<-EOT
    Value of POSTGRES_DB inside the job. NOT COSMETIC — eighteen of the nineteen revisions
    (all but 0006) read it as their target-safety expectation:

        _EXPECTED_DB = os.environ.get("POSTGRES_DB", "ithina_dis_db")

    and REFUSE to run when it does not match `current_database()`. The staging database is
    `thalamus`, so leaving this at the code default would fail every revision including the
    only outstanding one. The guard additionally hard-blocks `ithina_platform_db` (Customer
    Master) by name whatever this is set to.

    No default on purpose: this must be a conscious statement of which database is being
    migrated, matching the DSN in secret_admin_url. A default here would be a second source of
    truth for the same fact.
  EOT
}

variable "max_retries" {
  type        = number
  description = "0: a migration that fails must be looked at, not retried. Alembic runs each revision in a transaction, so a failure leaves the version unchanged and a blind retry would just fail again against the same cause."
  default     = 0
}

variable "task_timeout" {
  type        = string
  description = "600s matches migrate-synapse. DIS's chain is longer (19 revisions vs 4) but only outstanding revisions run; a full bootstrap against an empty database applies 16 DDL files and still lands well inside this."
  default     = "600s"
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
