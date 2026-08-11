output "job_name" {
  value       = google_cloud_run_v2_job.migrate_axon.name
  description = "Execute with: gcloud run jobs execute migrate-axon --region <REGION> --wait"
}

output "service_account_email" {
  value       = google_service_account.migrate_axon.email
  description = "The migration identity. If a future migration needs more than the admin DSN, grant it here rather than widening the orchestrator's."
}
