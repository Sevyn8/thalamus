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

# ============================================================================
# THE SAME TWO-URL AUTH0 TRAP APPLIES HERE, UNVERIFIED BUT LIKELY
# ============================================================================
# This service has two Cloud Run URLs like every other (a legacy
# <name>-<hash>-<regioncode>.a.run.app and the newer
# <name>-<projectnumber>.<region>.run.app), and it DOES do Auth0: the image bakes
# VITE_AUTH0_DOMAIN / _CLIENT_ID / _AUDIENCE at build time
# (dis/terraform/docker/dis-ui-ver2.Dockerfile).
#
# There is NO VITE_AUTH0_REDIRECT_URI build arg, which means the SPA almost
# certainly uses window.location.origin as its redirect_uri - so whichever host a
# user loads becomes the callback, and only the host registered in Auth0 works.
# cm-frontend hit exactly this and it presents as "The state parameter is
# invalid", naming the state rather than the hostname.
#
# NOT VERIFIED: the ver2 source is not in this repo (only dist/), so the
# redirect_uri could not be read. Check Auth0's Allowed Callback URLs for this
# client and confirm which of the two hosts is registered before sending anyone
# a link. lib/launcher/tiles.ts uses the 697546531605 form.
# ============================================================================

variable "image" {
  type        = string
  description = "Full container image reference. Defaults to the tag live on the service at import time. Built by dis/terraform/docker/cloudbuild-dis-ui-ver2.yaml, which pins an explicit vN and no floating `latest`."
  default     = "asia-south1-docker.pkg.dev/sevyn8-thalamus-staging/thalamus-images/dis-ui-ver2:v16"
}

variable "service_account_id" {
  type        = string
  description = "Account id for this service's DEDICATED runtime identity (P1-IAM-001A). It holds NO application IAM: this service reads no secret, calls no Google API, and talks to dis-ui-server over public HTTPS forwarding the browser's Auth0 bearer rather than a credential of its own. Serving static files, writing to stdout and having an image pulled by the Cloud Run service agent are not IAM-gated on the runtime identity, so an empty permission set is the correct one - not an oversight to be topped up later."
  default     = "dis-ui-ver2-sa"
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
