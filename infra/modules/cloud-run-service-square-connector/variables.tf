###############################################################################
# cloud-run-service-square-connector variables.
#
# The Square connector is a Cloud Run JOB: one execution is one trigger (mint
# ids -> pull Square -> CSV into bronze -> publish ingress.ready -> exit). It has
# no port, no probe and no scaling knobs.
#
# There are DELIBERATELY no run-target variables (tenant/store/source/template/
# run-key). A multi-tenant connector's terraform must not know a tenant's ids;
# the run target is supplied per execution via `gcloud run jobs execute --args`.
#
# DB connection is private-IP TCP through the connector (no socket, no
# cloudsql.client). POSTGRES_URL and SQUARE_APP_SECRET are secret-backed by
# reference.
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
  description = "Cloud Run v2 job name. This is the name `gcloud run jobs execute` targets."
  default     = "square-connector"
}

variable "service_account_id" {
  type        = string
  description = "account_id for the dedicated runtime service account (before the @project.iam.gserviceaccount.com suffix)."
  default     = "square-connector-sa"
}

variable "image" {
  type        = string
  description = "Full container image reference. Built from connectors/thalamus-square/Dockerfile with the MONOREPO ROOT as context."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/square-connector:v1"
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector id (module.network.vpc_connector_id / thalamus-vpcconn). Egress to the private Cloud SQL IP goes through this."
}

# --- Cloud Run Job sizing / execution policy ---

variable "max_retries" {
  type        = number
  description = "Task retries on failure. 0: a manually executed pull must fail loudly. Safe to raise (a same-run_key retry mints the same connector_run_id and the query-based dedup collapses it), but a silent retry hides the first failure."
  default     = 0
}

variable "task_timeout" {
  type        = string
  description = "Per-task timeout. A sandbox catalog pull is small; this is a runaway bound, not a tuning knob."
  default     = "600s"
}

variable "cpu" {
  type        = string
  description = "CPU limit per task."
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Memory limit per task."
  default     = "512Mi"
}

# --- Connector runtime configuration (plain env; the EXACT names the code reads) ---

variable "dis_expected_database" {
  type        = string
  description = "DIS_EXPECTED_DATABASE. The parameterized dis-rls guard (session.py:52, which defaults to ithina_dis_db and aborts at engine construction otherwise). thalamus for the consolidated deploy."
  default     = "thalamus"
}

variable "ingress_ready_topic" {
  type        = string
  description = "INGRESS_READY_TOPIC. The provisioned topic short name the connector publishes ingress.ready to. Resolved as an import-time module constant (csv_ingest_worker/config.py:57, default ingress.ready), so it MUST equal the topic's name or the publish goes nowhere."
  default     = "dis-ingress-ready"
}

variable "square_api_base_url" {
  type        = string
  description = "SQUARE_API_BASE_URL. The Square host: the API base, the OAuth base, AND the environment stamp (SquareOAuthConfig derives environment = sandbox iff the host contains squareupsandbox). Prod is https://connect.squareup.com."
  default     = "https://connect.squareupsandbox.com"
}

variable "square_client_id" {
  type        = string
  description = "SQUARE_CLIENT_ID: the Square application ID (public). Must be the SAME app id dis-ui-server connects with, or the refresh grant is rejected."
}

variable "bronze_bucket_name" {
  type        = string
  description = "GCS_BUCKET_BRONZE. The bronze bucket name; also the resource the SA gets storage.objectAdmin on (the connector WRITES the object)."
}

variable "ingress_topic_id" {
  type        = string
  description = "The ingress.ready topic id the SA gets pubsub.publisher on."
}

# --- Secret Manager references (values live in Secret Manager, created out of
#     band; TF references them by name only). ---

variable "secret_database_url" {
  type        = string
  description = "Secret Manager secret name holding the full SQLAlchemy POSTGRES_URL (private-IP TCP, sslmode=require)."
  default     = "dis-database-url"
}

variable "secret_square_app_secret" {
  type        = string
  description = "Secret Manager secret name holding the Square application secret (client_secret), used for the OAuth refresh grant. Shared with dis-ui-server; created out of band."
  default     = "square-app-secret"
}
