###############################################################################
# gcs-tenant-documents variables.
#
# Bucket holding CM tenant onboarding documents. Uploads and downloads go
# direct to GCS via V4 signed URLs minted by CM (no object-content proxying
# through the backend). project/region/origin are variables (never hardcoded),
# consistent with the sibling cloud-run-service-* modules.
###############################################################################

variable "project_id" {
  type        = string
  description = "GCP project id (Thalamus staging: sevyn8-thalamus-staging)."
}

variable "region" {
  type        = string
  description = "Bucket location (a GCP region, e.g. asia-south1)."
}

variable "bucket_name" {
  type        = string
  description = "Globally-unique bucket name for tenant documents."
}

variable "frontend_origin" {
  type        = string
  description = "Exact origin (scheme+host, no trailing slash) allowed to PUT via a signed URL from the browser. Set to the CM frontend origin."
}
