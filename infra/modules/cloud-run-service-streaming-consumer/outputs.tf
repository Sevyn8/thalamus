output "service_url" {
  value       = google_cloud_run_v2_service.streaming_consumer.uri
  description = "HTTPS URL of the streaming-consumer service (serves /healthz; real work is the pull loop)."
}

output "service_name" {
  value = google_cloud_run_v2_service.streaming_consumer.name
}

output "service_account_email" {
  value       = google_service_account.streaming_consumer.email
  description = "Runtime SA (secretAccessor on dis-database-url, objectViewer on bronze, subscriber on the ingress sub, project pubsub.viewer)."
}
