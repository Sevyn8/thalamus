###############################################################################
# cloud-sql: ONE shared Postgres instance for the consolidated Thalamus data
# plane. One instance, one database, three application roles. No schemas here:
# CM's Alembic creates `core`; DIS's Alembic creates its 8 schemas (audit,
# bronze, canonical, config, identity_mirror, quarantine, staging, telemetry).
# Extensions and the canonical public.uuidv7() are a privileged setup-SQL step
# run once post-create (see infra/db-setup/), NOT managed here.
#
# Merged posture:
#   - POSTGRES_16, ENTERPRISE edition (DIS).
#   - private IP only, ssl_mode ENCRYPTED_ONLY (CM).
#   - cloudsql.iam_authentication=on (DIS; helps the RLS session-GUC pattern).
#   - deletion_protection=true.
#   - backups + PITR + maintenance window + query insights (CM, the more
#     complete config).
#
# Three roles, each a google_sql_user with a generated password stored in Secret
# Manager. All rely on Cloud SQL's default posture: app users are NOT granted
# SUPERUSER or the cloudsqlsuperuser role and are NOT BYPASSRLS, so each is
# NOSUPERUSER NOBYPASSRLS as required by CM's D-03 / DIS's RLS contract. Per-
# schema grants are done by each app's Alembic; the mirror-reader grant is a
# post-migration step (infra/db-setup/02_mirror_reader_grant.sql).
###############################################################################

# One generated password per role. override_special reserved to URL/shell-safe
# characters (carried from CM) so passwords embed into postgresql:// URLs without
# percent-encoding footguns.
resource "random_password" "cm_app" {
  length           = 40
  special          = true
  override_special = "_-."
}

resource "random_password" "dis_app" {
  length           = 40
  special          = true
  override_special = "_-."
}

resource "random_password" "dis_mirror_reader" {
  length           = 40
  special          = true
  override_special = "_-."
}

resource "google_sql_database_instance" "this" {
  name                = var.instance_name
  project             = var.project_id
  region              = var.region
  database_version    = "POSTGRES_16"
  deletion_protection = var.deletion_protection

  settings {
    edition           = "ENTERPRISE"
    tier              = var.tier
    availability_type = var.availability_type
    disk_type         = "PD_SSD"
    disk_size         = var.disk_size_gb
    disk_autoresize   = true

    # Private IP only, encrypted transport only.
    ip_configuration {
      ipv4_enabled                                  = false
      private_network                               = var.network_id
      enable_private_path_for_google_cloud_services = true
      ssl_mode                                      = "ENCRYPTED_ONLY"
    }

    backup_configuration {
      enabled                        = true
      start_time                     = "03:00"
      point_in_time_recovery_enabled = true
      transaction_log_retention_days = 7
      backup_retention_settings {
        retained_backups = 7
        retention_unit   = "COUNT"
      }
    }

    maintenance_window {
      day          = 7 # Sunday
      hour         = 4 # 04:00 instance-local
      update_track = "stable"
    }

    insights_config {
      query_insights_enabled  = true
      query_string_length     = 1024
      record_application_tags = false
      record_client_address   = false
    }

    database_flags {
      # Helps the RLS session-GUC pattern both apps use (DIS carried this).
      name  = "cloudsql.iam_authentication"
      value = "on"
    }

    database_flags {
      name  = "log_min_duration_statement"
      value = "1000"
    }

    user_labels = {
      environment = var.environment
      service     = "thalamus-shared"
      managed-by  = "terraform"
    }
  }

  # Private IP requires the Service Networking peering to exist first.
  depends_on = [var.private_service_connection]
}

# The single shared database. Named neutrally (not either app's current db name):
# BOTH apps must point their DATABASE_URL at this one db. CM's core schema and
# DIS's 8 schemas coexist here.
resource "google_sql_database" "shared" {
  name      = var.database_name
  project   = var.project_id
  instance  = google_sql_database_instance.this.name
  charset   = "UTF8"
  collation = "en_US.UTF8"
}

# --- Application roles (schemas + per-schema grants are Alembic's job) --------

resource "google_sql_user" "cm_app" {
  name     = var.cm_app_user_name
  project  = var.project_id
  instance = google_sql_database_instance.this.name
  password = random_password.cm_app.result
}

resource "google_sql_user" "dis_app" {
  name     = var.dis_app_user_name
  project  = var.project_id
  instance = google_sql_database_instance.this.name
  password = random_password.dis_app.result
}

resource "google_sql_user" "dis_mirror_reader" {
  name     = var.dis_mirror_reader_user_name
  project  = var.project_id
  instance = google_sql_database_instance.this.name
  password = random_password.dis_mirror_reader.result
}

# --- Secret Manager: one container + version per role password ---------------

locals {
  role_passwords = {
    (var.cm_app_user_name)            = random_password.cm_app.result
    (var.dis_app_user_name)           = random_password.dis_app.result
    (var.dis_mirror_reader_user_name) = random_password.dis_mirror_reader.result
  }
}

resource "google_secret_manager_secret" "db_password" {
  for_each  = local.role_passwords
  project   = var.project_id
  secret_id = "${var.secret_prefix}-${each.key}-password"

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_password" {
  for_each    = local.role_passwords
  secret      = google_secret_manager_secret.db_password[each.key].id
  secret_data = each.value
}
