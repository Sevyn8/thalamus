###############################################################################
# cloud-run-service-dis-ui-ver2 variables.
#
# Every default below is the value READ FROM THE LIVE SERVICE via the Cloud Run
# v2 REST API, because this module exists to describe a service that already
# runs. A default that disagrees with live shows up as a plan diff, which is what
# this module is verified against.
#
# No secrets appear here, and the service references no Secret Manager secrets at
# all - the single env var is a plain URL.
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
  default     = "dis-ui-ver2"
}

variable "image" {
  type        = string
  description = "Full container image reference. Defaults to the tag live on the service at import time. Built by dis/terraform/docker/cloudbuild-dis-ui-ver2.yaml, which pins an explicit vN and no floating `latest`."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/dis-ui-ver2:v16"
}

variable "service_account_email" {
  type        = string
  description = "Runtime identity. This is the DEFAULT COMPUTE SA, which is what the live service runs as - NOT a dedicated identity like every other service in this tree. Recorded, on the ledger as HIGH, and deliberately not changed in this slice (it is a template field, so changing it rolls a revision)."
  default     = "697546531605-compute@developer.gserviceaccount.com"
}

# --- The coupled backend URL (see the COUPLING block in main.tf) ---

variable "dis_ui_server_base_url" {
  type        = string
  description = "DIS_UI_SERVER_BASE_URL - the dis-ui-server origin that nginx reverse-proxies /api to at RUNTIME (envsubst at container start, not a build arg). The proxy forwards the browser's Auth0 bearer and presents no credential of its own, so it depends on dis-ui-server's allUsers invoker binding; see the COUPLING block in main.tf before changing that posture."
  default     = "https://dis-ui-server-mjiqp4br4a-el.a.run.app"
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
  description = "Per-revision minimum instances. 0 = scale to zero for staging cost. The live service reports no minInstanceCount, which is 0. A static SPA behind nginx has no pull loop to keep alive, so scale-to-zero is correct here (unlike the DIS workers)."
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
