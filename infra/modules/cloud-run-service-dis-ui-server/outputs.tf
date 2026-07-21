output "service_url" {
  value       = google_cloud_run_v2_service.dis_ui_server.uri
  description = "Public HTTPS URL of the dis-ui-server service. Curl <url>/healthz to verify liveness."
}

output "service_name" {
  value = google_cloud_run_v2_service.dis_ui_server.name
}

output "service_account_email" {
  value       = google_service_account.dis_ui_server.email
  description = "Runtime SA identity (secretAccessor on dis-database-url, objectAdmin on bronze, publisher on the csv topic)."
}
