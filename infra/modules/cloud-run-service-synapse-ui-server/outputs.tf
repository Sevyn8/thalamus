output "service_url" {
  value       = google_cloud_run_v2_service.synapse_ui_server.uri
  description = "The BFF's URL. cm-frontend takes this as SYNAPSE_BFF_URL and uses it as the audience for the ID token it mints — the two must be the same string or Cloud Run rejects the token."
}

output "service_account_email" {
  value       = google_service_account.synapse_ui_server.email
  description = "This service's dedicated runtime identity. Holds secretAccessor on the reader DSN only."
}
