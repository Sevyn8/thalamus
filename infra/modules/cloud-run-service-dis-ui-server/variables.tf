###############################################################################
# cloud-run-service-dis-ui-server variables.
#
# Defaults carry the values grounded this session (image tag, DB-name guard
# override, csv topic short name). POSTGRES_URL is secret-backed by reference
# (never a value here). The DB connection is private-IP TCP through the VPC
# connector, so there is NO /cloudsql socket and NO roles/cloudsql.client.
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
  default     = "dis-ui-server"
}

variable "service_account_id" {
  type        = string
  description = "account_id for the dedicated runtime service account (before the @project.iam.gserviceaccount.com suffix)."
  default     = "dis-ui-server-sa"
}

variable "image" {
  type        = string
  description = "Full container image reference. Defaults to the v1 tag pushed this session."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/dis-ui-server:v2"
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

# --- dis-ui-server runtime configuration (plain env; the EXACT names config.py reads) ---

variable "dis_expected_database" {
  type        = string
  description = "DIS_EXPECTED_DATABASE. The parameterized dis-rls guard: must be the DB the connection lands in. thalamus for the consolidated deploy; without it /readyz fails."
  default     = "thalamus"
}

variable "dis_auth_mode" {
  type        = string
  description = "DIS_AUTH_MODE. STUB or AUTH0. AUTH0 turns on the RS256/JWKS verifier (real Auth0 tokens); requires jwt_issuer + jwt_audience."
  default     = "AUTH0"
}

variable "jwt_issuer" {
  type        = string
  description = "JWT_ISSUER. Auth0 tenant issuer (ends with '/'; the backend derives AUTH0_JWKS_URL from it). Required when dis_auth_mode=AUTH0."
  default     = "https://sevyn8.us.auth0.com/"
}

variable "jwt_audience" {
  type        = string
  description = "JWT_AUDIENCE. The DIS API audience Auth0 tokens are minted for. Required when dis_auth_mode=AUTH0."
  default     = "https://api.dis.sevyn8.com"
}

# --- Vertex/Gemini mapping suggestions ---
#
# THESE TWO ARE A PAIR AND MUST BOTH BE SET. config.py reads each with a plain
# `os.environ.get(...) or None`, so either one alone is silently None and the
# suggester still falls back to the mechanical matcher — with no error anywhere. The
# symptom of getting this half-right is the wizard quietly saying "basic match",
# which is indistinguishable from not having configured it at all.
#
# HOW THE REGION WAS ESTABLISHED, because the obvious routes do not work and this
# note is meant to save the next person the same forty minutes:
#
#   - asia-south1 was verified by a LIVE generateContent call against
#     sevyn8-thalamus-staging, after enabling aiplatform.googleapis.com. It returned
#     200 with real generated content. That is the only check that actually proves
#     serving.
#   - The docs pages (vertex-ai/generative-ai/docs/learn/locations and the
#     gemini-2.5-flash model card) render only navigation when fetched, so they
#     cannot be read programmatically.
#   - The publisher-model descriptor
#     (GET /v1beta1/publishers/google/models/gemini-2.5-flash) is NOT an
#     availability oracle: it returns HTTP 200 launchStage=GA for every location
#     tried, INCLUDING "global". It describes the model's existence, not whether a
#     region serves it. Do not use a 200 from it as evidence.
#
# asia-southeast1 and asia-northeast1 were also verified as working fallbacks, so
# there is somewhere to go if asia-south1 ever drops the model.
#
# BUT MOVING OFF asia-south1 IS A RESIDENCY TRADE, NOT A FREE SWITCH. The prompt
# carries sample_values — three real cell values per column from the tenant's
# uploaded CSV (SAMPLE_VALUES = 3 in ver2's analyze-csv.ts), not just column names.
# On asia-south1 those values stay in Mumbai, the same region as the database, the
# bronze bucket and every service. Any other region, or the "global" endpoint, means
# tenant cell values leaving that region. Decide that deliberately.

variable "gemini_vertex_project" {
  type        = string
  description = "GEMINI_VERTEX_PROJECT. The Vertex AI project for mapping suggestions. Auth is ambient ADC from this service's SA (no API key), so the SA also needs roles/aiplatform.user granted out of band. Paired with gemini_vertex_location: either alone is silently ignored."
  default     = "sevyn8-thalamus-staging"
}

variable "gemini_vertex_location" {
  type        = string
  description = "GEMINI_VERTEX_LOCATION. asia-south1, VERIFIED by a live generateContent call rather than from documentation (see the block above: the docs render only navigation and the publisher-model descriptor returns 200 for every location including global). asia-southeast1 / asia-northeast1 are verified fallbacks, but moving off asia-south1 sends tenant cell values out of the region."
  default     = "asia-south1"
}

variable "csv_received_topic" {
  type        = string
  description = "CSV_RECEIVED_TOPIC. The provisioned topic short name the app publishes csv.received to. Must equal the inline topic's name."
  default     = "dis-csv-received"
}

variable "bronze_bucket_name" {
  type        = string
  description = "GCS_BUCKET_BRONZE. The bronze bucket name; also the resource the SA gets storage.objectAdmin on."
}

variable "csv_topic_id" {
  type        = string
  description = "The csv.received topic id (projects/<p>/topics/<name>) the SA gets pubsub.publisher on. Distinct from csv_received_topic (which is the app-facing short name)."
}

# --- Secret Manager reference (value lives in Secret Manager, created out of
#     band; TF references it by name only). ---

variable "secret_database_url" {
  type        = string
  description = "Secret Manager secret name holding the full SQLAlchemy POSTGRES_URL (private-IP TCP, sslmode=require)."
  default     = "dis-database-url"
}

# --- Square OAuth connect (S2). client_id + redirect_uri are per-env inputs; base URL and
#     the two secret names ride defaults. The app secret and state-signing key are
#     secret-backed env (created out of band, referenced by name). ---

variable "square_client_id" {
  type        = string
  description = "SQUARE_CLIENT_ID: the Square application ID (public). Sandbox app id for staging."
}

variable "square_oauth_base_url" {
  type        = string
  description = "SQUARE_OAUTH_BASE_URL: the Square OAuth host. Sandbox default; prod is https://connect.squareup.com."
  default     = "https://connect.squareupsandbox.com"
}

variable "square_oauth_redirect_uri" {
  type        = string
  description = "SQUARE_OAUTH_REDIRECT_URI: the exact redirect URL registered in the Square dashboard (the SPA callback route)."
}

variable "secret_square_app_secret" {
  type        = string
  description = "Secret Manager secret name holding the Square application secret (client_secret). Created out of band."
  default     = "square-app-secret"
}

variable "secret_oauth_state_key" {
  type        = string
  description = "Secret Manager secret name holding the HMAC key that signs the OAuth state token. Created out of band."
  default     = "dis-ui-oauth-state-key"
}

# --- Clover OAuth connect (C3). Same shape as the Square block: client_id + redirect_uri
#     are per-env inputs, base URL and the secret name ride defaults. The state-signing key
#     is SHARED with Square and is not repeated here. ---

variable "clover_client_id" {
  type        = string
  description = "CLOVER_CLIENT_ID: the Clover application ID (public). Sandbox app id for staging."
}

variable "clover_oauth_base_url" {
  type        = string
  description = "CLOVER_OAUTH_BASE_URL: the Clover OAuth host. NOT just a host - thalamus_clover_oauth derives the token record's environment stamp from whether it contains 'sandbox', so set it deliberately. Clover hosts are per-region as well as per-environment."
  default     = "https://sandbox.dev.clover.com"
}

variable "clover_oauth_redirect_uri" {
  type        = string
  description = "CLOVER_OAUTH_REDIRECT_URI: the exact redirect URL registered in the Clover dashboard. Use the LAUNCH path (/connectors/clover/launch) - it is the form proven accepted, and CloverCallback forwards to it."
}

variable "secret_clover_app_secret" {
  type        = string
  description = "Secret Manager secret name holding the Clover application secret. Created out of band."
  default     = "clover-app-secret"
}
