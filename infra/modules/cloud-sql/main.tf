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
# Five roles, each a google_sql_user with a generated password stored in Secret
# Manager. All rely on Cloud SQL's default posture: app users are NOT granted
# SUPERUSER or the cloudsqlsuperuser role and are NOT BYPASSRLS, so each is
# NOSUPERUSER NOBYPASSRLS as required by CM's D-03 / DIS's RLS contract. Per-
# schema grants are done by each app's Alembic; the two READ-ONLY roles' grants are
# post-migration steps (infra/db-setup/sql/02_mirror_reader_grant.sql and
# sql/03_synapse_reader_grant.sql).
#
# THE NOBYPASSRLS CLAIM ABOVE IS AN ASSERTION ABOUT CLOUD SQL'S DEFAULT, not something
# Terraform enforces. It is independently checked at runtime: dis-rls reads rolsuper /
# rolbypassrls from pg_roles on first use of every engine and raises RlsContextError if
# either is true, so a bypassing role fails LOUDLY on its first query rather than silently
# voiding tenant isolation. Both read-role grant files also carry a manual verification
# query for it. Two mechanisms, because the failure this prevents is invisible.
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

resource "random_password" "synapse_reader" {
  length           = 40
  special          = true
  override_special = "_-."
}

resource "random_password" "synapse_writer" {
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

# Synapse's read-only role. Same shape as dis_mirror_reader, deliberately: that role is the
# precedent for "a peer plane reads a schema it does not own", and a second pattern would be
# a second thing to keep correct.
#
# NOTHING RUNS AS THIS ROLE IN PRODUCTION YET. No Cloud Run service or job binds it, no
# service account holds secretAccessor on its DSN. It exists so Synapse's integration tests
# can run against a real database as the identity the resolvers are DESIGNED for, instead of
# borrowing ithina_dis_user — which holds full DML on canonical and would make a read-only
# analytics plane's tests prove nothing about its read-only-ness.
#
# The GRANTS are NOT here: SELECT on exactly two canonical tables, applied post-migration by
# infra/db-setup/sql/03_synapse_reader_grant.sql (canonical does not exist until DIS's Alembic
# has run). Same split as dis_mirror_reader, same reason.
resource "google_sql_user" "synapse_reader" {
  name     = var.synapse_reader_user_name
  project  = var.project_id
  instance = google_sql_database_instance.this.name
  password = random_password.synapse_reader.result
}

# Synapse's WRITE role, and a SECOND role rather than a widened reader.
#
# synapse_reader holds SELECT on canonical. Giving it INSERT anywhere would mean the engine the
# RESOLVERS hold could write, and "resolvers never write" is currently only a code property
# (a grep test for INSERT/UPDATE/DELETE imports). Two roles make it a RUNTIME property: one
# process holds two engines, and an INSERT added to a resolver by mistake fails at the database.
# The converse matters as much — this role holds NOTHING on canonical, so the action log cannot
# read tenant data even by accident.
#
# INSERT AND NOTHING ELSE, including no SELECT: appending needs none (ON CONFLICT DO NOTHING
# requires no SELECT privilege; RETURNING would, so the log does not use it). Grants are applied
# by Synapse's own alembic chain and re-asserted by
# infra/db-setup/sql/04_synapse_writer_grant.sql, not here.
resource "google_sql_user" "synapse_writer" {
  name     = var.synapse_writer_user_name
  project  = var.project_id
  instance = google_sql_database_instance.this.name
  password = random_password.synapse_writer.result
}

# --- Secret Manager: one container + version per role password ---------------

locals {
  role_passwords = {
    (var.cm_app_user_name)            = random_password.cm_app.result
    (var.dis_app_user_name)           = random_password.dis_app.result
    (var.dis_mirror_reader_user_name) = random_password.dis_mirror_reader.result
    (var.synapse_reader_user_name)    = random_password.synapse_reader.result
    (var.synapse_writer_user_name)    = random_password.synapse_writer.result
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
