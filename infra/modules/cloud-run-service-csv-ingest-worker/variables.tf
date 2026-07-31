###############################################################################
# cloud-run-service-csv-ingest-worker variables.
#
# csv-ingest-worker is a long-running Pub/Sub PULL consumer deployed as an
# always-on Cloud Run Service (RUN_HEALTH_SERVER=true serves /healthz for the
# probe alongside the pull loop). D58: the query-based dedup is single-instance
# only, so min=max=1 and cpu_idle=false are CORRECTNESS constraints, not tuning.
# DB connection is private-IP TCP through the connector (no socket, no
# cloudsql.client). POSTGRES_URL is secret-backed by reference.
###############################################################################

variable "project_id" {
  type        = string
  description = "GCP project id. Thalamus staging is sevyn8-thalamus-staging; never ithina-dis-cm."
}

variable "region" {
  type        = string
  description = "Region for the Cloud Run service (asia-south1 for Thalamus staging)."
}

variable "service_name" {
  type        = string
  description = "Cloud Run v2 service name."
  default     = "csv-ingest-worker"
}

variable "service_account_id" {
  type        = string
  description = "account_id for the dedicated runtime service account (before the @project.iam.gserviceaccount.com suffix)."
  default     = "csv-ingest-worker-sa"
}

variable "image" {
  type        = string
  description = "Full container image reference. Built from dis/terraform/docker/csv-ingest-worker.Dockerfile with the dis/ WORKSPACE ROOT as build context (the service is a uv-workspace member). The module default is a FLOOR, not the deployed tag — the env pins the live one. A description naming a specific version is guaranteed to rot, so this names the build path instead."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/csv-ingest-worker:v1"
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector id (module.network.vpc_connector_id / thalamus-vpcconn). Egress to the private Cloud SQL IP goes through this."
}

# --- Cloud Run sizing (D58: single-instance correctness constraint) ---

variable "min_instances" {
  type        = number
  description = "Minimum instances. Pinned to 1: a scale-to-zero pull worker would stop consuming when idle."
  default     = 1
}

variable "max_instances" {
  type        = number
  description = "Maximum instances. Pinned to 1 (D58): the query-based dedup is single-instance only. Do not raise."
  default     = 1
}

variable "cpu" {
  type        = string
  description = "CPU limit per instance."
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Memory limit per instance."
  default     = "512Mi"
}

# --- Worker runtime configuration (plain env; the EXACT names config.py reads) ---

variable "dis_expected_database" {
  type        = string
  description = "DIS_EXPECTED_DATABASE. The parameterized dis-rls guard for the bronze write path. thalamus for the consolidated deploy."
  default     = "thalamus"
}

variable "csv_received_subscription" {
  type        = string
  description = "CSV_RECEIVED_SUBSCRIPTION. The provisioned pull subscription short name the worker subscribes to. Must equal the subscription's name."
  default     = "dis-csv-received-sub"
}

variable "ingress_ready_topic" {
  type        = string
  description = "INGRESS_READY_TOPIC. The provisioned topic short name the worker publishes ingress.ready to. Must equal the topic's name."
  default     = "dis-ingress-ready"
}

variable "bronze_bucket_name" {
  type        = string
  description = "GCS_BUCKET_BRONZE. The bronze bucket name; also the resource the SA gets storage.objectAdmin on."
}

variable "subscription_id" {
  type        = string
  description = "The csv.received pull subscription id the SA gets pubsub.subscriber on."
}

variable "ingress_topic_id" {
  type        = string
  description = "The ingress.ready topic id the SA gets pubsub.publisher on."
}

# --- Secret Manager reference (value lives in Secret Manager, created out of
#     band; TF references it by name only). ---

variable "secret_database_url" {
  type        = string
  description = "Secret Manager secret name holding the full SQLAlchemy POSTGRES_URL (private-IP TCP, sslmode=require)."
  default     = "dis-database-url"
}
