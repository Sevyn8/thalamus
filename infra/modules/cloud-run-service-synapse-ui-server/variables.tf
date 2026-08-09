variable "project_id" {
  type        = string
  description = "The Thalamus GCP project id."
}

variable "region" {
  type        = string
  description = "Region for the Cloud Run service."
  default     = "asia-south1"
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name. Also the audience cm-frontend mints its ID token for."
  default     = "synapse-ui-server"
}

variable "image" {
  type        = string
  description = "Fully-qualified image pinned to an explicit vN tag. Never :latest — a floating tag is how thalamus-images/dis-ui-ver2:latest came to point at v7 while v15 was serving."
}

variable "service_account_id" {
  type        = string
  description = "Account id for this service's DEDICATED runtime identity. Holds secretAccessor on THREE secrets: the synapse_reader DSN, the synapse_lifecycle DSN (slice 5d) and the synapse_provisioner DSN (slice 5e). NOT the writer, which is the orchestrator's identity and holds INSERT on synapse.actions. Each write credential is one verb on one table: lifecycle appends to synapse.action_events so the console can record a snooze, dismissal or acknowledgement, and provisioner inserts into synapse.provision so the console can enable a monitor. Neither can UPDATE anything, so neither can edit or undo what it wrote."
  default     = "synapse-ui-server"
}

variable "caller_service_account_email" {
  type        = string
  description = "The identity permitted to invoke this service. Today this is the project's DEFAULT COMPUTE service account, because cm-frontend has no dedicated one — so the binding admits every default-compute workload in the project, not cm-frontend alone. It removes ANONYMOUS access, which is the substance of the standing HIGH finding, and nothing more. See the module header."
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector. Cloud SQL is reached over the private IP through this, which is why the service needs no roles/cloudsql.client."
}

variable "secret_reader_url" {
  type        = string
  description = "Secret Manager id of the synapse_reader DSN. Read-only on two canonical tables plus synapse.actions, provision and run."
  default     = "synapse-reader-database-url"
}

variable "secret_lifecycle_url" {
  type        = string
  description = "Secret Manager id of the synapse_lifecycle DSN. INSERT on synapse.action_events and nothing else. Arrived with slice 5d; the service refuses to start without it."
  default     = "synapse-lifecycle-database-url"
}

variable "secret_provisioner_url" {
  type        = string
  description = "Secret Manager id of the synapse_provisioner DSN. INSERT on synapse.provision, plus SELECT on identity_mirror.tenants and canonical.store_sku_current_position because the enablement pre-flight runs in the same transaction as the insert and cannot execute without them. No UPDATE, so the console can enable a monitor and cannot disable one or edit a timezone. Not synapse_writer and not synapse_lifecycle. Created OUT OF BAND like the other two DSN secrets; grants come from infra/db-setup/sql/05_synapse_provisioner_grant.sql. Arrived with slice 5e; the service refuses to start without it."
  default     = "synapse-provisioner-database-url"
}

variable "cm_api_base_url" {
  type        = string
  description = "CM_API_BASE_URL - Customer Master's origin, called SERVER-SIDE by the provisioning gate. Provisioning is authorized by asking CM's /api/v1/me/can-do whether the caller holds ADMIN.TENANTS.CONFIGURE.GLOBAL, forwarding the caller's own Auth0 token; the gate denies on any failure including a CM outage. Synapse defines no permission of its own and holds no copy of CM's model. Pass module.cm_service.service_url by reference rather than a copied literal, so the two cannot drift. No trailing slash: config.py strips one anyway, because a doubled slash produces a 404 that reads like a missing endpoint. The service refuses to start without it, because a service that cannot evaluate its own authorization must not serve the route."
}

variable "dis_expected_database" {
  type        = string
  description = "The database dis-rls will accept. Must be the consolidated `thalamus`; its own default is the pre-consolidation ithina_dis_db, which no longer exists."
  default     = "thalamus"
}

variable "jwt_issuer" {
  type        = string
  description = "Auth0 issuer URL. The JWKS URL is DERIVED from it in config.py rather than configured separately: a JWKS URL disagreeing with the issuer verifies tokens from the wrong directory."
}

variable "jwt_audience" {
  type        = string
  description = "The API identifier this service accepts tokens for."
}

variable "min_instances" {
  type        = number
  description = "Zero. A superadmin console is used occasionally; a cold start is cheaper than a warm instance holding a database pool open all night."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Bounded because every request opens a Cloud SQL connection through the reader role."
  default     = 4
}

variable "cpu" {
  type        = string
  default     = "1"
  description = "The work is IO-bound on Postgres, not compute-bound."
}

variable "memory" {
  type        = string
  default     = "512Mi"
  description = "Reads are aggregated in SQL and bounded at 500 rows; nothing large is held in memory."
}

variable "client" {
  type        = string
  default     = "terraform"
  description = "Declared because it is Optional and NOT Computed in the provider: undeclared, it diffs on every plan forever."
}

variable "client_version" {
  type        = string
  default     = ""
  description = "See `client`."
}
