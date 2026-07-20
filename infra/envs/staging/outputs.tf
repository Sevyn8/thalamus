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
