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

output "dis_ui_server_url" {
  value       = module.dis_ui_server_service.service_url
  description = "dis-ui-server Cloud Run URL. Verify liveness with: curl <url>/healthz"
}

output "dis_ui_server_service_account_email" {
  value       = module.dis_ui_server_service.service_account_email
  description = "dis-ui-server runtime SA (secretAccessor on dis-database-url, objectAdmin on bronze, publisher on the csv topic)."
}

output "csv_ingest_worker_url" {
  value       = module.csv_ingest_worker_service.service_url
  description = "csv-ingest-worker Cloud Run URL (serves /healthz; real work is the pull loop)."
}

output "csv_ingest_worker_service_account_email" {
  value       = module.csv_ingest_worker_service.service_account_email
  description = "csv-ingest-worker runtime SA (secretAccessor, objectAdmin on bronze, subscriber on the csv sub, publisher on the ingress topic, project pubsub.viewer)."
}

output "streaming_consumer_url" {
  value       = module.streaming_consumer_service.service_url
  description = "streaming-consumer Cloud Run URL (serves /healthz; real work is the pull loop)."
}

output "streaming_consumer_service_account_email" {
  value       = module.streaming_consumer_service.service_account_email
  description = "streaming-consumer runtime SA (secretAccessor, objectViewer on bronze, subscriber on the ingress sub, project pubsub.viewer)."
}

output "square_connector_job_name" {
  value       = module.square_connector_job.job_name
  description = "Square connector Cloud Run JOB name. Execute one pull with: gcloud run jobs execute <name> --region asia-south1 --args=\"--tenant-id,<uuid>,--store-id,<uuid>,--source-id,<slug>,--template-id,<uuid>,--run-key,<key>,--store-code,<code>\" --wait"
}

output "square_connector_service_account_email" {
  value       = module.square_connector_job.service_account_email
  description = "square-connector runtime SA (secretAccessor on dis-database-url + square-app-secret, project squareTokenVaultRefresher, objectAdmin on bronze, publisher on the ingress topic; deliberately no pubsub.viewer)."
}
