###############################################################################
# Thalamus staging variables.
#
# project_id / region / zone / labels are consumed by the provider now and by
# every Wave 1-4 module later. org_id / billing_account are consumed by
# infra/bootstrap (not by resources here); they are declared for parity and
# single-source reference, and are harmless if unused this wave. state_prefix is
# documentation only (backend.tf hardcodes the literal; backend blocks cannot
# interpolate variables).
###############################################################################

variable "project_id" {
  type        = string
  description = "GCP project id for Thalamus staging. Never ithina-dis-cm."
  default     = "sevyn8-thalamus-staging"
}

variable "region" {
  type        = string
  description = "Primary region for all Thalamus staging resources."
  default     = "asia-south1"
}

variable "zone" {
  type        = string
  description = "Zone for zonal resources (later waves)."
  default     = "asia-south1-c"
}

variable "org_id" {
  type        = string
  description = "GCP organization id (sevyn8.com). Reference only here; consumed by infra/bootstrap."
  default     = "395217984150"
}

variable "billing_account" {
  type        = string
  description = "Billing account id. Reference only here; consumed by infra/bootstrap."
  default     = "016691-555E7E-B5AB24"
}

variable "state_prefix" {
  type        = string
  description = "Documentation of the remote-state prefix. backend.tf hardcodes this literal (backend blocks cannot use variables)."
  default     = "thalamus/staging"
}

variable "labels" {
  type        = map(string)
  description = "Default labels applied to every resource that supports labels."
  default = {
    workload    = "thalamus"
    env         = "staging"
    cost_center = "sevyn8"
  }
}

###############################################################################
# Wave 1: network
###############################################################################

variable "name_prefix" {
  type        = string
  description = "Prefix for shared network resource names."
  default     = "thalamus"
}

variable "subnet_cidr" {
  type        = string
  description = "Primary subnet CIDR for the shared VPC."
  default     = "10.20.0.0/24"
}

variable "connector_cidr" {
  type        = string
  description = "The /28 for the Serverless VPC Access connector (must not overlap subnet_cidr)."
  default     = "10.8.0.0/28"
}

###############################################################################
# Wave 1: Cloud SQL (shared instance + shared database + three roles)
###############################################################################

variable "cloud_sql_instance_name" {
  type        = string
  description = "Cloud SQL instance name."
  default     = "thalamus-pg"
}

variable "database_name" {
  type        = string
  description = "The single shared database name. Neutral; BOTH apps point DATABASE_URL here."
  default     = "thalamus"
}

variable "cloud_sql_tier" {
  type        = string
  description = "Cloud SQL machine tier. See modules/cloud-sql for the default rationale (db-custom-1-3840, smallest modern ENTERPRISE tier for POSTGRES_16)."
  default     = "db-custom-1-3840"
}

variable "cloud_sql_disk_size_gb" {
  type        = number
  description = "Cloud SQL data disk size in GB."
  default     = 10
}

variable "cloud_sql_availability_type" {
  type        = string
  description = "ZONAL for staging; REGIONAL for prod."
  default     = "ZONAL"
}

variable "cloud_sql_deletion_protection" {
  type        = bool
  description = "Prevent accidental instance destroy."
  default     = true
}

###############################################################################
# Wave 2: CM (cm-backend) Cloud Run service
###############################################################################

variable "cm_image" {
  type        = string
  description = "CM container image, consumed by BOTH the cm-backend service and the migrate-cm job (D6: one pin, so a migration cannot run a different build than the app it migrates for). Bumping this bumps both."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/cm-backend:v13"
}

variable "cm_app_region" {
  type        = string
  description = "CM APP_REGION. Legal values EU|US|LOCAL ONLY (data-residency bucket, NOT the GCP region). asia-south1 is invalid and crashes CM on boot. Confirm the intended bucket."
  default     = "US"
}

# The three Auth0 lazy values below are TRACKED HERE ON PURPOSE, which reverses
# this project's earlier posture of keeping them in the untracked tfvars. None
# carries credential material: a client id is a public identifier and a connection
# name is a label, and the first two are already plaintext env vars on the live
# cm-backend container, so tracking them exposes nothing a Cloud Run reader cannot
# already see. Anything genuinely secret (the paired client SECRET, the SendGrid
# key, DATABASE_URL) goes to Secret Manager and is referenced by name - never to a
# tracked tfvars and never to a variable default.
#
# They are here because a clean-slate apply that left them empty would deploy
# cm-backend with no Auth0 Management config at all: lazy means not boot-blocking,
# so it would come up healthy and then fail the first invite.

variable "cm_auth0_mgmt_client_id" {
  type        = string
  description = "AUTH0_MGMT_CLIENT_ID ('Cortex CM Backend M2M' client id). A public identifier, not a credential; the paired client secret lives in Secret Manager as cm-auth0-mgmt-client-secret. Lazy (not boot-blocking), so an empty value fails at first use rather than at boot."
  default     = "bnlGD4qRoNohOaJans7xZ9H1u9m2Zz9N"
}

variable "cm_auth0_mgmt_db_connection" {
  type        = string
  description = "AUTH0_MGMT_DB_CONNECTION - the Auth0 database-connection NAME (a label, not a secret). Lazy, so an empty value fails at first use rather than at boot."
  default     = "Username-Password-Authentication"
}

variable "cm_auth0_ticket_result_url" {
  type        = string
  description = "AUTH0_TICKET_RESULT_URL - where Auth0 sends the user after an invite password-set. Points at the CM frontend's login route. Lazy, so an empty value fails at first use rather than at boot."
  default     = "https://cm-frontend-697546531605.asia-south1.run.app/auth/login"
}

variable "cm_frontend_image" {
  type        = string
  description = "cm-frontend container image. The tag live on the imported service; cm-frontend is deployed by gcloud, so bump this in the same commit as any deploy."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/cm-frontend:v17"
}

variable "cm_documents_bucket_name" {
  type        = string
  description = "Globally-unique GCS bucket name for CM tenant onboarding documents (Slice 3). Feeds CM's GCS_DOCUMENTS_BUCKET once the cm module gains that env var (see the TODO in main.tf)."
  default     = "sevyn8-thalamus-cm-documents-staging"
}

variable "cm_documents_frontend_origin" {
  type        = string
  description = "Exact origin allowed to PUT documents via signed URL from the browser (CM frontend origin; scheme+host, no trailing slash)."
  default     = "https://cm-frontend-697546531605.asia-south1.run.app"
}

###############################################################################
# Wave 3: DIS (dis-ui-server) Cloud Run service
###############################################################################

variable "dis_ui_server_image" {
  type        = string
  description = "dis-ui-server container image. Defaults to the v1 tag pushed this session."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/dis-ui-server:v7"
}

variable "mirror_sync_consumer_image" {
  type        = string
  description = "mirror-sync-consumer container image (the Cloud Run JOB). Built from dis/terraform/docker/mirror-sync-consumer.Dockerfile with the dis/ WORKSPACE ROOT as build context, via cloudbuild-mirror-sync-consumer.yaml with an explicit _TAG and no floating `latest`."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/mirror-sync-consumer:v1"
}

variable "dis_ui_ver2_image" {
  type        = string
  description = "dis-ui-ver2 (SPA) container image. The tag live on the imported service. Built by dis/terraform/docker/cloudbuild-dis-ui-ver2.yaml with an explicit _TAG=vN and no floating `latest`; bump this in the same commit as any deploy."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/dis-ui-ver2:v16"
}

variable "csv_ingest_worker_image" {
  type        = string
  description = "csv-ingest-worker container image. Defaults to the v1 tag pushed this session."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/csv-ingest-worker:v3"
}

variable "streaming_consumer_image" {
  type        = string
  description = "streaming-consumer container image. Defaults to the v1 tag pushed this session."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/streaming-consumer:v2"
}

# ONE Clover host for BOTH services, deliberately.
#
# dis-ui-server reads it as CLOVER_OAUTH_BASE_URL and the clover-connector reads it as
# CLOVER_API_BASE_URL - two names for the same host, in two codebases. Both construct a
# CloverOAuthClient, which derives environment = "sandbox" if "sandbox" in base_url else
# "production" and STAMPS IT ONTO THE SAME per-tenant token record: the BFF at connect, the
# connector on every rotation. Two writers of one field from two differently-named vars is
# a field with two sources of truth, and it would oscillate on whichever service wrote last.
#
# Nothing reads the stamp today (grepped: it is written, round-tripped and displayed, never
# branched on), so this is not a live correctness bug - but a single variable prevents the
# drift rather than documenting it. The code-level split, and the identical Square split
# (SQUARE_OAUTH_BASE_URL / SQUARE_API_BASE_URL), are on the ledger.
variable "clover_base_url" {
  type        = string
  description = "The Clover host for BOTH dis-ui-server and the clover-connector. Sandbox for staging; production is per-region. Shared so the two services cannot stamp different environments onto one token record."
  default     = "https://sandbox.dev.clover.com"
}

variable "square_connector_image" {
  type        = string
  description = "square-connector container image (the Cloud Run JOB). Built from connectors/thalamus-square/Dockerfile with the MONOREPO ROOT as build context."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/square-connector:v3"
}

variable "clover_connector_image" {
  type        = string
  description = "clover-connector container image (the Cloud Run JOB). Built from connectors/thalamus-clover/Dockerfile with the MONOREPO ROOT as build context."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/clover-connector:v2"
}
