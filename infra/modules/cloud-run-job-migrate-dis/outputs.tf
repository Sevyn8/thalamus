output "job_name" {
  value       = google_cloud_run_v2_job.migrate_dis.name
  description = "Execute with: gcloud run jobs execute migrate-dis --region <REGION> --wait"
}

output "service_account_email" {
  value       = google_service_account.migrate_dis.email
  description = "The migration identity. If a future migration needs more than the admin DSN, grant it here rather than widening any DIS workload's."
}
