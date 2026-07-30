output "service_url" {
  value       = google_cloud_run_v2_service.dis_ui_ver2.uri
  description = "Public HTTPS URL of the DIS UI. Publicly callable at the IAM layer (allUsers invoker); the SPA's Auth0 session gates access to data."
}

output "service_name" {
  value = google_cloud_run_v2_service.dis_ui_ver2.name
}

output "service_account_email" {
  value       = google_cloud_run_v2_service.dis_ui_ver2.template[0].service_account
  description = "Runtime identity actually in use. This is the DEFAULT COMPUTE SA, not a dedicated one - see the ledger."
}
