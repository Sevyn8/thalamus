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
  description = "Account id for this service's DEDICATED runtime identity. Holds secretAccessor on TWO secrets: the synapse_reader DSN and, since slice 5d, the synapse_lifecycle DSN. Not the writer. The lifecycle grant is INSERT on synapse.action_events and nothing else, so the console can record a snooze, dismissal or acknowledgement WITHOUT being able to write synapse.actions, which is the orchestrator's table via synapse_writer."
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
