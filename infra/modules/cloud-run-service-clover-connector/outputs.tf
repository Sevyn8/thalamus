output "job_name" {
  value       = google_cloud_run_v2_job.clover_connector.name
  description = "Cloud Run job name. Execute with: gcloud run jobs execute <name> --region <region> --args=..."
}

output "service_account_email" {
  value       = google_service_account.clover_connector.email
  description = "Runtime SA (secretAccessor on dis-database-url + clover-app-secret, cloverTokenVaultRefresher at project level, objectAdmin on bronze, publisher on the ingress topic; no pubsub.viewer)."
}

output "token_vault_role_id" {
  value       = google_project_iam_custom_role.clover_token_vault_refresher.role_id
  description = "The project custom role granting read, refresh-and-persist, and PRUNE on the per-tenant Clover OAuth token secrets."
}
