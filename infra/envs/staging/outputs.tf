###############################################################################
# Wave 1 outputs. cloud_sql_connection_name feeds Alembic + the Cloud Run
# connector in later waves; password_secret_ids are what the app DATABASE_URL
# secrets are assembled from (Wave 2+).
###############################################################################

output "network_id" {
  value = module.network.network_id
}

output "vpc_connector_id" {
  value       = module.network.vpc_connector_id
  description = "Serverless VPC Access connector, for Cloud Run services in later waves."
}

output "cloud_sql_connection_name" {
  value       = module.cloud_sql.connection_name
  description = "project:region:instance for Alembic + the Cloud SQL connector."
}

output "cloud_sql_private_ip" {
  value = module.cloud_sql.private_ip
}

output "database_name" {
  value = module.cloud_sql.database_name
}

output "app_user_names" {
  value = module.cloud_sql.app_user_names
}

output "password_secret_ids" {
  value       = module.cloud_sql.password_secret_ids
  description = "Secret Manager ids holding each role's generated password."
}

output "artifact_registry_url" {
  value       = module.artifact_registry.repo_url
  description = "Base URL for image pushes (push cm-backend + DIS images here)."
}

output "cm_service_url" {
  value       = module.cm_service.service_url
  description = "CM Cloud Run URL. Verify with: curl <url>/api/v1/health"
}

output "cm_service_account_email" {
  value       = module.cm_service.service_account_email
  description = "CM runtime SA (holds secretAccessor on the three cm-* secrets)."
}
