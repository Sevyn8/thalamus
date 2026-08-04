output "instance_name" {
  value = google_sql_database_instance.this.name
}

output "connection_name" {
  value       = google_sql_database_instance.this.connection_name
  description = "INSTANCE connection name (project:region:instance) for the Cloud SQL connector + Alembic."
}

output "private_ip" {
  value = google_sql_database_instance.this.private_ip_address
}

output "database_name" {
  value = google_sql_database.shared.name
}

output "app_user_names" {
  value = {
    cm                = google_sql_user.cm_app.name
    dis               = google_sql_user.dis_app.name
    dis_mirror_reader = google_sql_user.dis_mirror_reader.name
    synapse_reader    = google_sql_user.synapse_reader.name
    synapse_writer    = google_sql_user.synapse_writer.name
  }
}

output "password_secret_ids" {
  description = "Secret Manager secret ids holding each role's generated password."
  value       = { for k, s in google_secret_manager_secret.db_password : k => s.id }
}
