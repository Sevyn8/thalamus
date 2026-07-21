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

# --- Wave 2: Artifact Registry (shared Docker repo for cm-backend + DIS images) ---

module "artifact_registry" {
  source = "../../modules/artifact-registry"

  project_id = var.project_id
  region     = var.region
}

# --- Wave 2: CM (cm-backend) Cloud Run service (AUTH0 mode) ---
#
# Egress to the private Cloud SQL IP rides module.network.vpc_connector_id
# (thalamus-vpcconn). DATABASE_URL / Auth0 M2M secret / SendGrid key are the
# out-of-band Secret Manager secrets (cm-database-url,
# cm-auth0-mgmt-client-secret, cm-sendgrid-api-key), referenced by name.

module "cm_service" {
  source = "../../modules/cloud-run-service-cm"

  project_id       = var.project_id
  region           = var.region
  image            = var.cm_image
  vpc_connector_id = module.network.vpc_connector_id

  # APP_REGION is a CM residency bucket (EU|US|LOCAL), NOT the GCP region.
  app_region = var.cm_app_region

  # Lazy Auth0 values, not recorded in the repo; empty until supplied in tfvars.
  auth0_mgmt_client_id     = var.cm_auth0_mgmt_client_id
  auth0_mgmt_db_connection = var.cm_auth0_mgmt_db_connection
  auth0_ticket_result_url  = var.cm_auth0_ticket_result_url
}

# --- Wave 3: DIS (dis-ui-server) durable infra + Cloud Run service ---
#
# dis-ui-server needs a bronze bucket (GCS_BUCKET_BRONZE) and the csv.received
# topic (CSV_RECEIVED_TOPIC) as boot env values, plus the pre-created
# dis-database-url secret (POSTGRES_URL, private-IP TCP). DB egress rides the
# shared connector; DIS_EXPECTED_DATABASE=thalamus satisfies the dis-rls guard.

# Bronze bucket: CSV uploads land here. Uniform access + public-access
# prevention satisfy the org policies. No lifecycle rules (staging, low volume).
resource "google_storage_bucket" "dis_bronze" {
  project                     = var.project_id
  name                        = "thalamus-dis-bronze-staging"
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
}

# csv.received topic: dis-ui-server publishes the upload envelope here.
resource "google_pubsub_topic" "csv_received" {
  project = var.project_id
  name    = "dis-csv-received"
}

# ingress.ready topic: csv-ingest-worker publishes here after the bronze write.
resource "google_pubsub_topic" "ingress_ready" {
  project = var.project_id
  name    = "dis-ingress-ready"
}

# Pull subscription on csv.received: csv-ingest-worker consumes from here.
# Staging plain retry (no dead_letter_policy).
resource "google_pubsub_subscription" "csv_received_sub" {
  project              = var.project_id
  name                 = "dis-csv-received-sub"
  topic                = google_pubsub_topic.csv_received.id
  ack_deadline_seconds = 30
}

# Pull subscription on ingress.ready: streaming-consumer consumes from here
# (completing the pipeline after csv-ingest-worker publishes). Staging plain
# retry (no dead_letter_policy).
resource "google_pubsub_subscription" "ingress_ready_sub" {
  project              = var.project_id
  name                 = "dis-ingress-ready-sub"
  topic                = google_pubsub_topic.ingress_ready.id
  ack_deadline_seconds = 30
}

module "dis_ui_server_service" {
  source = "../../modules/cloud-run-service-dis-ui-server"

  project_id       = var.project_id
  region           = var.region
  image            = var.dis_ui_server_image
  vpc_connector_id = module.network.vpc_connector_id

  # Referencing the inline resources' attributes makes Terraform create the
  # bucket + topic (and their IAM) before the service.
  bronze_bucket_name = google_storage_bucket.dis_bronze.name
  csv_topic_id       = google_pubsub_topic.csv_received.id
  csv_received_topic = google_pubsub_topic.csv_received.name
}

module "csv_ingest_worker_service" {
  source = "../../modules/cloud-run-service-csv-ingest-worker"

  project_id       = var.project_id
  region           = var.region
  image            = var.csv_ingest_worker_image
  vpc_connector_id = module.network.vpc_connector_id

  # Referencing the inline resources makes Terraform create the bucket + topic +
  # subscription (and their IAM) before the worker.
  bronze_bucket_name = google_storage_bucket.dis_bronze.name
  subscription_id    = google_pubsub_subscription.csv_received_sub.id
  ingress_topic_id   = google_pubsub_topic.ingress_ready.id
}

module "streaming_consumer_service" {
  source = "../../modules/cloud-run-service-streaming-consumer"

  project_id       = var.project_id
  region           = var.region
  image            = var.streaming_consumer_image
  vpc_connector_id = module.network.vpc_connector_id

  # Referencing the inline resources makes Terraform create the bucket +
  # subscription (and their IAM) before the consumer.
  bronze_bucket_name = google_storage_bucket.dis_bronze.name
  subscription_id    = google_pubsub_subscription.ingress_ready_sub.id
}
