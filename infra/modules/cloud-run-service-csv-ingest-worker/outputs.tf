output "service_url" {
  value       = google_cloud_run_v2_service.csv_ingest_worker.uri
  description = "HTTPS URL of the csv-ingest-worker service (serves /healthz; real work is the pull loop)."
}

output "service_name" {
  value = google_cloud_run_v2_service.csv_ingest_worker.name
}

output "service_account_email" {
  value       = google_service_account.csv_ingest_worker.email
  description = "Runtime SA (secretAccessor on dis-database-url, objectAdmin on bronze, subscriber on the csv sub, publisher on the ingress topic, project pubsub.viewer)."
}
