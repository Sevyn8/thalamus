###############################################################################
# cloud-run-service-streaming-consumer variables.
#
# streaming-consumer is a long-running Pub/Sub PULL consumer deployed as an
# always-on Cloud Run Service (RUN_HEALTH_SERVER=true serves /healthz alongside
# the pull loop). It subscribes to ingress.ready and dual-writes canonical rows
# (hot + event) plus quarantine to the DB; it PUBLISHES NOTHING (terminal DB
# writer). Unlike csv-ingest-worker, this consumer is
# concurrency-safe, so max_instances is a var (default 1) that is safe to raise.
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
  default     = "streaming-consumer"
}

variable "service_account_id" {
  type        = string
  description = "account_id for the dedicated runtime service account (before the @project.iam.gserviceaccount.com suffix)."
  default     = "streaming-consumer-sa"
}

variable "image" {
  type        = string
  description = "Full container image reference. Built from dis/terraform/docker/streaming-consumer.Dockerfile with the dis/ WORKSPACE ROOT as build context (the service is a uv-workspace member). The module default is a FLOOR, not the deployed tag — the env pins the live one. A description naming a specific version is guaranteed to rot, so this names the build path instead."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/streaming-consumer:v1"
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector id (module.network.vpc_connector_id / thalamus-vpcconn). Egress to the private Cloud SQL IP goes through this."
}

# --- Cloud Run sizing ---

variable "min_instances" {
  type        = number
  description = "Minimum instances. Pinned to 1: a scale-to-zero pull worker would stop consuming when idle."
  default     = 1
}

variable "max_instances" {
  type        = number
  description = "Maximum instances. Default 1: a single consumer is sufficient for staging. NOT a correctness constraint (streaming-consumer is concurrency-safe: atomic dual-write, read-time latest-wins); safe to raise, unlike csv-ingest-worker's single-instance dedup hard pin."
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

# --- Consumer runtime configuration (plain env; the EXACT names config.py reads) ---

variable "dis_expected_database" {
  type        = string
  description = "DIS_EXPECTED_DATABASE. The parameterized dis-rls guard for the canonical dual-write path. thalamus for the consolidated deploy."
  default     = "thalamus"
}

variable "ingress_ready_subscription" {
  type        = string
  description = "INGRESS_READY_SUBSCRIPTION. The provisioned pull subscription short name the consumer subscribes to. Must equal the subscription's name."
  default     = "dis-ingress-ready-sub"
}

variable "bronze_bucket_name" {
  type        = string
  description = "GCS_BUCKET_BRONZE. The bronze bucket name; also the resource the SA gets storage.objectViewer (read-only) on."
}

variable "subscription_id" {
  type        = string
  description = "The ingress.ready pull subscription id the SA gets pubsub.subscriber on."
}

# --- Secret Manager reference (value lives in Secret Manager, created out of
#     band; TF references it by name only). ---

variable "secret_database_url" {
  type        = string
  description = "Secret Manager secret name holding the full SQLAlchemy POSTGRES_URL (private-IP TCP, sslmode=require)."
  default     = "dis-database-url"
}
