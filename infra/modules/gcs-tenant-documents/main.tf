###############################################################################
# gcs-tenant-documents: the bucket for CM tenant onboarding documents.
#
# Uniform bucket-level access (IAM only, no ACLs), object versioning on
# (retain overwritten/deleted object generations), public access prevention
# enforced (org-policy satisfying; no anonymous access), and a CORS rule so
# the frontend origin can PUT directly to a signed URL. No lifecycle rules
# (staging; low volume). IAM (which SA can read/write) is granted by the
# caller in the env wiring, not here, so the module stays reusable.
###############################################################################

resource "google_storage_bucket" "documents" {
  project                     = var.project_id
  name                        = var.bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  versioning {
    enabled = true
  }

  cors {
    origin          = [var.frontend_origin]
    method          = ["PUT"]
    response_header = ["Content-Type"]
    max_age_seconds = 3600
  }
}
