output "job_name" {
  value       = google_cloud_run_v2_job.migrate_cm.name
  description = "Cloud Run job name. Execute with: gcloud run jobs execute migrate-cm --region <region> --project <project> --wait"
}

output "job_id" {
  value = google_cloud_run_v2_job.migrate_cm.id
}

output "image" {
  value       = google_cloud_run_v2_job.migrate_cm.template[0].template[0].containers[0].image
  description = "Image the migration actually runs. Shared with the cm-backend service by design (D6) so a migration cannot run a different build than the app it migrates for."
}
