output "bucket_name" {
  value       = google_storage_bucket.documents.name
  description = "Tenant-documents bucket name. Feeds CM's GCS_DOCUMENTS_BUCKET and the runtime SA's storage.objectAdmin grant."
}

output "bucket_url" {
  value       = google_storage_bucket.documents.url
  description = "gs:// URL of the bucket."
}
