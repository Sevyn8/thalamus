output "job_name" {
  value       = google_cloud_run_v2_job.mirror_sync_consumer.name
  description = "Cloud Run job name. Execute with: gcloud run jobs execute mirror-sync-consumer --region <region> --project <project> --wait. No --args: the entrypoint takes none."
}

output "job_id" {
  value = google_cloud_run_v2_job.mirror_sync_consumer.id
}

output "service_account_email" {
  value       = google_service_account.mirror_sync_consumer.email
  description = "Dedicated runtime SA. Holds secretAccessor on exactly dis-mirror-reader-database-url and dis-database-url - deliberately NOT cm-database-url."
}
