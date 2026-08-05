output "job_name" {
  value       = google_cloud_run_v2_job.orchestrator.name
  description = "Cloud Run job name. `gcloud run jobs execute <this> --region <region> --args=--dry-run` is the hand-run, which takes the same code path the schedule does."
}

output "runtime_service_account_email" {
  value       = google_service_account.orchestrator.email
  description = "The job's runtime identity. Holds secretAccessor on the two Synapse DSN secrets and nothing else."
}

output "scheduler_service_account_email" {
  value       = google_service_account.scheduler.email
  description = "The identity Cloud Scheduler authenticates as. Holds run.invoker on the job resource only."
}

output "scheduler_job_name" {
  value       = google_cloud_scheduler_job.orchestrator_daily.name
  description = "Cloud Scheduler job. `gcloud scheduler jobs run <this> --location <region>` forces a fire without waiting for the cron — which is how the first firing gets OBSERVED rather than assumed."
}
