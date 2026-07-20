###############################################################################
# Thalamus staging: module wiring.
#
# Wave 1 (this file): the shared data plane. network (one fresh VPC) then
# cloud-sql (one instance, one database, three roles). Schemas, extensions,
# uuidv7, and the mirror-reader grant are NOT here: extensions + uuidv7 are the
# privileged setup SQL (infra/db-setup/sql/01_...), schemas are each app's
# Alembic, and the mirror-reader grant is the post-migration SQL
# (infra/db-setup/sql/02_...). See infra/db-setup/README.md for run order.
#
# Waves 2-4 add secrets/pubsub/buckets/service-accounts/artifact-registry and
# the Cloud Run services, reusing module.network.vpc_connector_id and
# module.cloud_sql.connection_name.
###############################################################################

module "network" {
  source = "../../modules/network"

  project_id     = var.project_id
  region         = var.region
  name_prefix    = var.name_prefix
  subnet_cidr    = var.subnet_cidr
  connector_cidr = var.connector_cidr
}

module "cloud_sql" {
  source = "../../modules/cloud-sql"

  project_id          = var.project_id
  region              = var.region
  instance_name       = var.cloud_sql_instance_name
  database_name       = var.database_name
  tier                = var.cloud_sql_tier
  disk_size_gb        = var.cloud_sql_disk_size_gb
  availability_type   = var.cloud_sql_availability_type
  deletion_protection = var.cloud_sql_deletion_protection
  environment         = "staging"

  network_id                 = module.network.network_id
  private_service_connection = module.network.private_service_connection
}
