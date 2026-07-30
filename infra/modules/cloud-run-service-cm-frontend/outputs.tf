output "service_url" {
  value       = google_cloud_run_v2_service.cm_frontend.uri
  description = "Public HTTPS URL of the CM frontend. Publicly callable at the IAM layer (allUsers invoker); the app's Auth0 session gates access."
}

output "service_name" {
  value = google_cloud_run_v2_service.cm_frontend.name
}

output "service_account_email" {
  value       = google_cloud_run_v2_service.cm_frontend.template[0].service_account
  description = "Runtime identity actually in use. This is the DEFAULT COMPUTE SA, not a dedicated one - see the ledger."
}
