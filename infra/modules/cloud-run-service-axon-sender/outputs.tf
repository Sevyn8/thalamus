output "service_name" {
  description = "The deployed Cloud Run service name."
  value       = google_cloud_run_v2_service.axon_sender.name
}

output "service_account_email" {
  description = "The runtime service account. Holds subscriber on one subscription and accessor on two secrets, and nothing else."
  value       = google_service_account.axon_sender.email
}
