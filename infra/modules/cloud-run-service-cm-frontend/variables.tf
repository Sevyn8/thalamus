###############################################################################
# cloud-run-service-cm-frontend variables.
#
# Every default below is the value READ FROM THE LIVE SERVICE via the Cloud Run
# v2 REST API, because this module exists to describe a service that already
# runs. A default that disagrees with live would show up as a plan diff, which is
# the whole thing this module is verified against.
#
# None of these values is a secret. The two real secrets (Auth0 client secret and
# the session-cookie secret) are Secret Manager references, named here only by
# secret id.
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
  default     = "cm-frontend"
}

variable "image" {
  type        = string
  description = "Full container image reference. Defaults to the tag live on the service at import time."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/cm-frontend:v17"
}

variable "service_account_email" {
  type        = string
  description = "Runtime identity. This is the DEFAULT COMPUTE SA, which is what the live service runs as - NOT a dedicated identity like every other service in this tree. It holds secretAccessor on both cm-frontend-* secrets. Recorded, on the ledger, and deliberately not changed in this slice."
  default     = "697546531605-compute@developer.gserviceaccount.com"
}

# --- gcloud provenance (see main.tf divergence 4) ---

variable "client" {
  type        = string
  description = "The API's `client` field. 'gcloud' because the service was created by `gcloud run deploy`. Optional and NOT Computed in the provider, so it must be declared or every plan diffs."
  default     = "gcloud"
}

variable "client_version" {
  type        = string
  description = "The API's `client_version` field, set by whichever gcloud created/last-deployed the service. Declared for the same reason as `client`."
  default     = "569.0.0"
}

# --- Cloud Run sizing (staging) ---

variable "min_instances" {
  type        = number
  description = "Per-revision minimum instances. 0 = scale to zero for staging cost. The live service reports no minInstanceCount, which is 0."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Per-revision maximum instances. Small for staging; matches the live maxInstanceCount."
  default     = 2
}

variable "cpu" {
  type        = string
  description = "Container CPU limit."
  default     = "1000m"
}

variable "memory" {
  type        = string
  description = "Container memory limit."
  default     = "512Mi"
}

variable "timeout" {
  type        = string
  description = "Per-request timeout. 300s is the live value (Cloud Run's own default), not a tuned choice."
  default     = "300s"
}

variable "max_concurrency" {
  type        = number
  description = "Max concurrent requests per instance. 80 is the live value (Cloud Run's own default)."
  default     = 80
}

# --- Auth0 / app wiring (all public, all baked as plain env) ---

variable "auth0_domain" {
  type        = string
  description = "AUTH0_DOMAIN for the CM frontend's Auth0 tenant."
  default     = "sevyn8.us.auth0.com"
}

variable "auth0_client_id" {
  type        = string
  description = "AUTH0_CLIENT_ID for the CM frontend Auth0 application. A client id is a public identifier, not a credential; the paired secret is a Secret Manager reference."
  default     = "Kf8lFtALAydGeRWmvukwbXQbAUepPpsF"
}

variable "auth0_audience" {
  type        = string
  description = "AUTH0_AUDIENCE - the CM API's Auth0 audience."
  default     = "https://api.sevyn8.com"
}

variable "api_base_url" {
  type        = string
  description = "API_BASE_URL - the cm-backend origin the frontend calls server-side over public HTTPS. This is why the frontend needs no VPC connector."
  default     = "https://cm-backend-mjiqp4br4a-el.a.run.app"
}

variable "synapse_bff_url" {
  type        = string
  description = "SYNAPSE_BFF_URL - the Synapse read-only BFF's origin, called SERVER-SIDE by the /superadmin/synapse pages. Unlike API_BASE_URL this is never reached from a browser: the BFF is reached only server-side with a Google ID token minted from the metadata server, and its IAM invoker binding is the control. It is NOT internal-ingress: that was tried and was never satisfiable, because this service has no VPC connector and no direct VPC egress, so its requests leave over the public internet. See cloud-run-service-synapse-ui-server/main.tf for the full reasoning. THIS STRING DOUBLES AS THE ID-TOKEN AUDIENCE, so it must be the service's exact URI - which is why staging passes module.synapse_ui_server.service_url by reference rather than a copied literal. Empty disables the console cleanly: the pages render a named 'not reachable' notice rather than throwing."
  default     = ""
}

variable "app_base_url" {
  type        = string
  description = "APP_BASE_URL - the frontend's own origin, used to build Auth0 callback URLs. THIS IS THE CANONICAL URL AND THE SERVICE HAS TWO. Cloud Run gives every service both a legacy https://<name>-<hash>-<regioncode>.a.run.app and a newer https://<name>-<projectnumber>.<region>.run.app; only the value below is registered in Auth0's Allowed Callback URLs. STARTING A LOGIN AT THE OTHER ONE FAILS WITH 'The state parameter is invalid' - the state cookie is set on one host and the callback lands on the other - and that error names the state parameter rather than the hostname, so it reads as an Auth0 misconfiguration and costs a debugging session. cm-backend's CORS allows BOTH forms, so the legacy URL loads and behaves normally right up until the Auth0 round trip. Send people to this one."
  default     = "https://cm-frontend-697546531605.asia-south1.run.app"
}

# --- Secret Manager secret ids (values never enter Terraform state) ---

variable "secret_auth0_client_secret" {
  type        = string
  description = "Secret id holding AUTH0_CLIENT_SECRET for the CM frontend Auth0 application."
  default     = "cm-frontend-auth0-client-secret"
}

variable "secret_auth0_secret" {
  type        = string
  description = "Secret id holding AUTH0_SECRET, the session-cookie signing key."
  default     = "cm-frontend-auth0-secret"
}
