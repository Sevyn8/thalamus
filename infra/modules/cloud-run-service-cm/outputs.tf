output "service_url" {
  value       = google_cloud_run_v2_service.cm_backend.uri
  description = "Public HTTPS URL of the CM service. Curl <url>/api/v1/health to verify."
}

output "service_name" {
  value = google_cloud_run_v2_service.cm_backend.name
}

output "service_account_email" {
  value       = google_service_account.cm_backend.email
  description = "Runtime SA identity (holds secretAccessor on the three cm-* secrets)."
}
