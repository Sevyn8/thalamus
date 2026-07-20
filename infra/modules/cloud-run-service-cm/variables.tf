###############################################################################
# cloud-run-service-cm variables.
#
# Defaults carry the values verified this session (image tag, DB schema, Auth0
# issuer/audience/jwks, SendGrid from-address). The three tenant-specific Auth0
# values that are NOT recorded anywhere in the repo (mgmt client id, mgmt DB
# connection, ticket result_url) default to empty: they are lazy (checked when
# the Auth0 Management client / SendGrid sender is constructed, NOT at boot), so
# CM boots in AUTH0 mode without them. Empty optionals are OMITTED from the
# container env (see main.tf locals) so CM's pydantic-settings reads them as
# None rather than "".
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
  default     = "cm-backend"
}

variable "service_account_id" {
  type        = string
  description = "account_id for the dedicated runtime service account (before the @project.iam.gserviceaccount.com suffix)."
  default     = "cm-backend-sa"
}

variable "image" {
  type        = string
  description = "Full container image reference. Defaults to the v1 tag pushed this session."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/cm-backend:v1"
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector id (module.network.vpc_connector_id / thalamus-vpcconn). Egress to the private Cloud SQL IP goes through this."
}

# --- Cloud Run sizing (staging) ---

variable "min_instances" {
  type        = number
  description = "Minimum instances. 0 = scale to zero for staging cost."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Maximum instances. Small for staging."
  default     = 2
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

# --- CM runtime configuration (plain env; CM's EXACT config.py names) ---

variable "db_schema" {
  type        = string
  description = "DB_SCHEMA. CM tables live in this Postgres schema (search_path)."
  default     = "core"
}

variable "environment" {
  type        = string
  description = "ENVIRONMENT. One of local|development|staging|production (CM Literal)."
  default     = "staging"
}

variable "app_region" {
  type        = string
  description = "APP_REGION. CM Literal is EU|US|LOCAL ONLY (config.py:135). asia-south1 is NOT a legal value and would crash CM on boot. Pick the residency bucket this deployment belongs to."
  default     = "US"

  validation {
    condition     = contains(["EU", "US", "LOCAL"], var.app_region)
    error_message = "app_region must be one of EU, US, LOCAL (CM's Literal). It is a data-residency bucket, not a GCP region; asia-south1 is invalid and crashes CM on boot."
  }
}

variable "log_level" {
  type        = string
  description = "LOG_LEVEL."
  default     = "INFO"
}

variable "jwt_issuer" {
  type        = string
  description = "JWT_ISSUER. Auth0 tenant issuer; ends with '/'."
  default     = "https://sevyn8.us.auth0.com/"
}

variable "jwt_audience" {
  type        = string
  description = "JWT_AUDIENCE. Auth0 API identifier."
  default     = "https://api.sevyn8.com"
}

variable "auth0_jwks_url" {
  type        = string
  description = "AUTH0_JWKS_URL. Derivable from jwt_issuer by CM, but set explicitly here. <issuer>.well-known/jwks.json."
  default     = "https://sevyn8.us.auth0.com/.well-known/jwks.json"
}

variable "sendgrid_from_email" {
  type        = string
  description = "SENDGRID_FROM_EMAIL. Verified SendGrid sender identity."
  default     = "noreply@sevyn8.com"
}

# --- Lazy Auth0 values: NOT recorded in the repo; operator must supply. ---
# Empty => omitted from container env => CM reads None. CM boots fine without
# them in AUTH0 mode; provisioning / invite-send / email-sync fail at RUN time
# until set.

variable "auth0_mgmt_client_id" {
  type        = string
  description = "AUTH0_MGMT_CLIENT_ID. The 'Cortex CM Backend M2M' app client id. Lazy; supply before Slice-2 provisioning is exercised."
  default     = ""
}

variable "auth0_mgmt_db_connection" {
  type        = string
  description = "AUTH0_MGMT_DB_CONNECTION. Auth0 database-connection name (e.g. Username-Password-Authentication). Lazy; needed for user create + email sync."
  default     = ""
}

variable "auth0_ticket_result_url" {
  type        = string
  description = "AUTH0_TICKET_RESULT_URL. Post-password-set redirect for the invite ticket. Lazy; needed for invite-send (2d-send)."
  default     = ""
}

# --- Secret Manager references (secret VALUES live in Secret Manager, created
#     out-of-band this session; TF references them by name only). ---

variable "secret_database_url" {
  type        = string
  description = "Secret Manager secret name holding the full SQLAlchemy DATABASE_URL (sslmode=require)."
  default     = "cm-database-url"
}

variable "secret_auth0_mgmt_client_secret" {
  type        = string
  description = "Secret Manager secret name holding the Auth0 M2M client secret."
  default     = "cm-auth0-mgmt-client-secret"
}

variable "secret_sendgrid_api_key" {
  type        = string
  description = "Secret Manager secret name holding the SendGrid API key."
  default     = "cm-sendgrid-api-key"
}
