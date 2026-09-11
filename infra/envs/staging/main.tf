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
  gcs_documents_bucket             = module.cm_documents_bucket.bucket_name
  gcs_signer_service_account_email = "cm-backend-sa@sevyn8-thalamus-staging.iam.gserviceaccount.com"
  source                           = "../../modules/cloud-run-service-cm"

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

# --- Wave 2: CM tenant-documents bucket ---
#
# Bucket for CM tenant onboarding documents; uploads/downloads go direct to
# GCS via V4 signed URLs minted by CM. IAM is granted below to the cm runtime
# SA (module.cm_service.service_account_email): objectAdmin on the bucket, and
# serviceAccountTokenCreator on itself so keyless V4 signing (IAM signBlob)
# works from Cloud Run (no SA key file).
module "cm_documents_bucket" {
  source = "../../modules/gcs-tenant-documents"

  project_id      = var.project_id
  region          = var.region
  bucket_name     = var.cm_documents_bucket_name
  frontend_origin = var.cm_documents_frontend_origin
}

# CM runtime SA can read/write objects in the documents bucket.
resource "google_storage_bucket_iam_member" "cm_documents_object_admin" {
  bucket = module.cm_documents_bucket.bucket_name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${module.cm_service.service_account_email}"
}

# CM runtime SA can sign blobs AS ITSELF (V4 signed URLs via IAM signBlob).
# Constructed from the SA email (exported by the cm module) so this needs no
# edit to cloud-run-service-cm.
resource "google_service_account_iam_member" "cm_documents_token_creator" {
  service_account_id = "projects/${var.project_id}/serviceAccounts/${module.cm_service.service_account_email}"
  role               = "roles/iam.serviceAccountTokenCreator"
  member             = "serviceAccount:${module.cm_service.service_account_email}"
}

# --- Wave 2: CM Alembic migration Cloud Run JOB ---
#
# ADOPTED BY IMPORT, not created. migrate-cm was gcloud-managed, so a clean-slate
# apply of this project produced no way to bring the CM schema up. The module was
# written against the LIVE v2 API config and imported.
#
# Shares var.cm_image with module.cm_service by design (D6): one pin, so the
# migration cannot run a different build than the service it migrates for. It also
# means bumping cm_image bumps BOTH, which is the intended coupling.
#
# The job OVERRIDES the image's CMD (which starts uvicorn) with
# `alembic upgrade head`. See the block at the top of the module before touching
# command/args: without them the job hangs serving HTTP instead of migrating.
#
# Runs as cm-backend-sa, taken from the cm module's output so the SA exists first
# and already holds secretAccessor on cm-database-url.
module "migrate_cm_job" {
  source = "../../modules/cloud-run-job-migrate-cm"

  project_id            = var.project_id
  region                = var.region
  image                 = var.cm_image
  service_account_email = module.cm_service.service_account_email
  vpc_connector_id      = module.network.vpc_connector_id
}

# TODO(operator): wire the bucket name into the CM container env as
# GCS_DOCUMENTS_BUCKET (and optionally GCS_SIGNER_SERVICE_ACCOUNT_EMAIL =
# module.cm_service.service_account_email). The cloud-run-service-cm module
# builds its env from a FIXED set of typed variables (no generic env map), so
# this requires a two-line change to that module (a new gcs_documents_bucket
# variable + an optional_env entry). That module is intentionally NOT edited
# yet. Until applied, CM boots fine but the document endpoints return 503
# DOCUMENT_STORAGE_UNAVAILABLE.

# --- Wave 2: CM frontend (cm-frontend) Cloud Run service ---
#
# ADOPTED BY IMPORT, not created. cm-frontend has been serving from Cloud Run
# since before Terraform described it, so a clean-slate apply of this project
# used to produce no CM frontend at all. The module was written against the LIVE
# v2 API config and imported; its acceptance test is a plan with no changes.
#
# Runs as the DEFAULT COMPUTE SA (not a dedicated identity like every other
# service here) and is publicly callable via an allUsers invoker binding. Both
# are recorded facts about the live service, declared so Terraform describes
# reality; the SA is on the ledger to fix before production.
# --- Synapse: the read-only BFF behind the superadmin console ---
#
# INTERNAL INGRESS + AN IAM INVOKER BINDING, so this is the FIRST service in this
# project that is not anonymously reachable. Every other one carries an
# `allUsers` binding with the JWT as the sole gate — the standing HIGH finding.
# A new service is the cheapest moment not to inherit it.
#
# READ THE MODULE HEADER on what the invoker binding is actually worth: it names
# the DEFAULT COMPUTE identity, because that is what cm-frontend runs as, so it
# admits every default-compute workload in the project rather than cm-frontend
# alone. That is anonymous-access removed, not caller-restricted. The real fix is
# a dedicated SA for cm-frontend, which is its own slice with a window.
module "synapse_ui_server" {
  source = "../../modules/cloud-run-service-synapse-ui-server"

  project_id       = var.project_id
  region           = var.region
  image            = var.synapse_ui_server_image
  vpc_connector_id = module.network.vpc_connector_id

  # The identity permitted to invoke. Deliberately the SAME literal the frontend
  # module defaults its runtime identity to, so the two cannot drift into naming
  # different accounts — if cm-frontend ever gains a dedicated SA, both change
  # together or the binding stops matching the caller and the console 403s.
  caller_service_account_email = "697546531605-compute@developer.gserviceaccount.com"

  # The BFF verifies the SAME Auth0 tokens cm-frontend issues, so issuer and
  # audience are the frontend's values. A BFF pointed at a different directory
  # would reject every token the console can obtain.
  jwt_issuer   = "https://sevyn8.us.auth0.com/"
  jwt_audience = "https://api.sevyn8.com"

  # WHERE THE PROVISIONING GATE ASKS ITS QUESTION. The BFF forwards the
  # caller's own Auth0 token to CM's /api/v1/me/can-do and denies unless CM says
  # the caller holds ADMIN.TENANTS.CONFIGURE.GLOBAL. Synapse holds no copy of CM's
  # permission model.
  #
  # A RESOURCE REFERENCE, NOT A COPIED STRING, for the same reason synapse_bff_url
  # is one below: a hand-copied URL that drifts from the service produces a gate
  # that denies every enable, and since the gate fails closed the symptom is
  # "provisioning is broken for everyone" rather than anything naming a URL. The
  # reference also gives terraform the edge, so CM exists before the revision that
  # points at it.
  cm_api_base_url = module.cm_service.service_url

  # AXON. This service is the delivery plane's first PRODUCER: the enable route hands
  # the provisioning event to Axon, which carries it to on-call and writes its own ledger row.
  #
  # THE ON-CALL ADDRESS IS DELIBERATELY NOT var.alert_email. That variable belongs to
  # monitoring-alerts, which carries facts about PROCESSES and is detected and sent by Cloud
  # Monitoring, outside the system it watches. Axon carries facts about the DOMAIN. Sharing one
  # variable would couple the two and make it one edit away from the alert that Axon is down
  # being delivered by Axon. The two may resolve to the same inbox and must not be the same
  # variable; the duplication is the point.
  axon_platform_oncall_email = var.axon_platform_oncall_email
  # Referencing the topic's attribute makes Terraform create the lane before the
  # service that publishes to it, and scopes the publisher grant to that one topic.
  axon_send_topic = google_pubsub_topic.axon_send_requested.name
}

module "cm_frontend_service" {
  source = "../../modules/cloud-run-service-cm-frontend"

  project_id = var.project_id
  region     = var.region
  image      = var.cm_frontend_image

  # A RESOURCE REFERENCE, NOT A COPIED STRING. This value doubles as the
  # ID-token audience the frontend mints against, so a hand-copied URL that
  # drifted from the service would fail token validation at Cloud Run with a 403
  # that looks like a permissions problem rather than a stale constant.
  #
  # It also gives Terraform the dependency edge: the BFF is created before the
  # frontend revision that references it.
  synapse_bff_url = module.synapse_ui_server.service_url

  # AND THE IAM BINDING TOO, which the string reference alone does NOT order.
  # `service_url` only depends on the Cloud Run service; the invoker binding is a
  # sibling resource. Without this the frontend could roll a revision holding a
  # valid URL before the grant exists, and every first page load would 403.
  depends_on = [module.synapse_ui_server]
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

###############################################################################
# DEAD-LETTER LANES for the two DIS pull subscriptions.
#
# Both consumers route every non-terminal failure to a NACK
# (`except Exception` -> log.error -> nack, in each service's process_message).
# Until this landed there was no dead_letter_policy on either subscription, so a
# NON-TRANSIENT failure - a TypeError, a schema break - nacked, redelivered,
# failed identically, and did so FOREVER. Three artefacts already asserted a
# dead-letter backstop existed; none was ever provisioned.
#
# TWO lanes, not one shared topic. The failures are not interchangeable at 2am,
# and more concretely they have DIFFERENT REPLAY PROCEDURES: a dead csv.received
# message replays from its bronze row or a re-upload, while a dead ingress.ready
# message replays through the `ingress.resubmit` path that does not exist yet
#. One topic would force whoever drains it to demultiplex by envelope
# shape before they could act.
#
# BOTH IAM GRANTS BELOW ARE LOAD-BEARING. The Pub/Sub service agent needs
# publisher on the dead-letter TOPIC *and* subscriber on the SOURCE SUBSCRIPTION.
# roles/pubsub.serviceAgent, which the agent already holds project-wide, contains
# ZERO Pub/Sub permissions - verified: only iam.serviceAccounts.*,
# resourcemanager.projects.* and serviceusage.services.use. Miss either grant and
# the policy is a SILENT NO-OP: the config has it, `gcloud pubsub subscriptions
# describe` reports it, and messages redeliver forever anyway - indistinguishable
# from the bug being fixed. Note the provider's own field description mentions
# only the publish half, so following it alone yields a policy that never fires.
###############################################################################

# The Pub/Sub service agent. Not a member of any module's SA set - it is Google's
# own per-project agent, and it is what moves a dead message from a subscription
# to its dead-letter topic.
locals {
  pubsub_service_agent = "serviceAccount:service-${data.google_project.this.number}@gcp-sa-pubsub.iam.gserviceaccount.com"
}

data "google_project" "this" {
  project_id = var.project_id
}

# --- csv.received dead-letter lane ---

resource "google_pubsub_topic" "csv_received_dlq" {
  project = var.project_id
  name    = "dis-csv-received-dlq"
}

# A dead-letter topic with NO SUBSCRIPTION silently discards everything published
# to it, so this subscription is what makes the DLQ a queue rather than a drain.
# Nobody consumes it today; the point is that the messages survive until somebody
# does.
#   expiration_policy ttl = ""  -> never expire. The DEFAULT is 31 days of
#     INACTIVITY, and a queue nobody pulls is inactive by definition, so the
#     default would delete this subscription and its backlog a month in.
#   message_retention_duration  -> 31 days, the schema maximum (default is 7).
resource "google_pubsub_subscription" "csv_received_dlq_sub" {
  project                    = var.project_id
  name                       = "dis-csv-received-dlq-sub"
  topic                      = google_pubsub_topic.csv_received_dlq.id
  ack_deadline_seconds       = 30
  message_retention_duration = "2678400s"
  expiration_policy {
    ttl = ""
  }
}

resource "google_pubsub_topic_iam_member" "csv_dlq_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.csv_received_dlq.name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_service_agent
}

resource "google_pubsub_subscription_iam_member" "csv_received_sub_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.csv_received_sub.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_service_agent
}

# --- ingress.ready dead-letter lane ---

resource "google_pubsub_topic" "ingress_ready_dlq" {
  project = var.project_id
  name    = "dis-ingress-ready-dlq"
}

resource "google_pubsub_subscription" "ingress_ready_dlq_sub" {
  project                    = var.project_id
  name                       = "dis-ingress-ready-dlq-sub"
  topic                      = google_pubsub_topic.ingress_ready_dlq.id
  ack_deadline_seconds       = 30
  message_retention_duration = "2678400s"
  expiration_policy {
    ttl = ""
  }
}

resource "google_pubsub_topic_iam_member" "ingress_dlq_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.ingress_ready_dlq.name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_service_agent
}

resource "google_pubsub_subscription_iam_member" "ingress_ready_sub_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.ingress_ready_sub.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_service_agent
}

# --- the two source subscriptions ---

# Pull subscription on csv.received: csv-ingest-worker consumes from here.
#
# retry_policy is a PREREQUISITE for max_delivery_attempts, not a nicety. Delivery
# attempts are counted as 1 + NACKs, and poll_once nacks by setting
# ack_deadline_seconds = 0 (immediate redelivery) with no sleep on the loop's
# success path. With no retry_policy, attempts therefore accumulate at LOOP SPEED
# rather than wall-clock speed, and a 60-120s Cloud SQL restart would burn through
# the whole budget in seconds and dead-letter perfectly healthy messages.
#
# It also fixes something independent of the DLQ: immediate redelivery means a
# poison message loops HOT, burning CPU, DB connections and Pub/Sub quota as fast
# as the consumer can pull. The backoff cools that to one attempt per 10s rising
# to one per 600s.
#
# max_delivery_attempts = 20 (~2.3h to dead-letter under this backoff). Legal
# range is 5-100. DELIBERATELY LOWER than the ingress lane below; see the
# asymmetry note there.
# A MAIN LANE. IF YOU ADD ANOTHER ONE, ADD IT TO main_subscription_names IN THE
# monitoring_alerts MODULE CALL BELOW, or it ships with no stuck-message alert and nothing says
# so. The dead-letter policy matches "*-dlq-sub" and covers new DLQs by existing; the
# stuck-message policy cannot do the same for mains, because "every -sub except the DLQ ones"
# needs a negative lookahead and RE2 has none, so the mains are enumerated by hand. This is the
# one drift that enumeration does not close, and this comment is where it is closable by a human.
resource "google_pubsub_subscription" "csv_received_sub" {
  project              = var.project_id
  name                 = "dis-csv-received-sub"
  topic                = google_pubsub_topic.csv_received.id
  ack_deadline_seconds = 30

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.csv_received_dlq.id
    max_delivery_attempts = 20
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  depends_on = [
    google_pubsub_topic_iam_member.csv_dlq_publisher,
  ]
}

# Pull subscription on ingress.ready: streaming-consumer consumes from here
# (completing the pipeline after csv-ingest-worker publishes).
#
# max_delivery_attempts = 100 (~16h), FIVE TIMES the csv lane's 20, and the
# asymmetry is reasoned rather than arbitrary. This is the lane carrying the
# documented HOT_POSITION_MISSING self-heal: a first-seen-SKU position miss and
# the store-miss contract violation are DELIBERATELY excluded from the
# quarantine allowlist because "redelivery is their designed recovery" until
# the catalogue or position
# onboards. That gap is a HUMAN process - sales uploads at 5pm, catalogue lands
# the next morning - so 2.3h would dead-letter a message that was going to
# succeed. ~16h covers same-working-day onboarding.
#
# WHAT THIS CHANGES, ACCEPTED DELIBERATELY: the self-heal is no longer unbounded.
# A message whose dependency never arrives now dead-letters instead of retrying
# forever. That is an IMPROVEMENT, not a regression: today the wait is INVISIBLE
# and INDEFINITE - a chunk stuck four days looks like nothing at all, and if the
# catalogue never onboards it is the same infinite loop this policy exists to
# bound. After this, the message is VISIBLE in a DLQ, intact for 31 days, and
# replayable. The automatic path narrows; the observable path appears.
# A MAIN LANE. A new one must also be added to main_subscription_names in the monitoring_alerts
# module call below, or it has no stuck-message alert. See the note at csv_received_sub.
resource "google_pubsub_subscription" "ingress_ready_sub" {
  project              = var.project_id
  name                 = "dis-ingress-ready-sub"
  topic                = google_pubsub_topic.ingress_ready.id
  ack_deadline_seconds = 30

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.ingress_ready_dlq.id
    max_delivery_attempts = 100
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  depends_on = [
    google_pubsub_topic_iam_member.ingress_dlq_publisher,
  ]
}

###############################################################################
# AXON'S SEND LANE. Topic, subscription, dead-letter topic, dead-letter
# subscription, and both service-agent grants.
#
# WHY A QUEUE AT ALL. The send used to be called in-process from the enable
# route, and that shape named the hole in its own comment: if the LEDGER WRITE failed there was no
# row, possibly an email, and a successful enable, with nothing afterwards able to
# tell that anything was owed. A durable queue makes the intent survive the
# consumer, so a failed write nacks and is retried instead of evaporating.
#
# THE SHAPE IS streaming-consumer's, NOT the orchestrator's. A sender has no
# cadence; it has a queue. So this is a pull subscription drained by a Cloud Run
# SERVICE at min_instances = 1, not a scheduled job.
###############################################################################

resource "google_pubsub_topic" "axon_send_requested" {
  project = var.project_id
  name    = "axon-send-requested"
}

resource "google_pubsub_topic" "axon_send_requested_dlq" {
  project = var.project_id
  name    = "axon-send-requested-dlq"
}

# A dead-letter topic with NO SUBSCRIPTION silently discards everything published
# to it, so this subscription is what makes the DLQ a queue rather than a drain.
# Both non-default settings are load-bearing, exactly as on the two DIS lanes:
#   expiration_policy ttl = ""   -> the subscription never expires. The default is
#     31 days of INACTIVITY, and a queue nobody pulls is inactive by definition.
#   message_retention_duration   -> 31 days, the schema maximum (default is 7).
resource "google_pubsub_subscription" "axon_send_requested_dlq_sub" {
  project                    = var.project_id
  name                       = "axon-send-requested-dlq-sub"
  topic                      = google_pubsub_topic.axon_send_requested_dlq.id
  ack_deadline_seconds       = 30
  message_retention_duration = "2678400s"
  expiration_policy {
    ttl = ""
  }
}

# BOTH GRANTS ARE LOAD-BEARING AND THE FAILURE IS SILENT. The Pub/Sub service
# agent needs publisher on the dead-letter TOPIC *and* subscriber on the SOURCE
# SUBSCRIPTION. roles/pubsub.serviceAgent contains ZERO Pub/Sub permissions (this
# was verified when the DIS lanes were built). Miss either one and the policy is a
# NO-OP that `gcloud pubsub subscriptions describe` still reports as configured,
# and messages redeliver forever, indistinguishable from the bug it fixes.
resource "google_pubsub_topic_iam_member" "axon_dlq_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.axon_send_requested_dlq.name
  role    = "roles/pubsub.publisher"
  member  = local.pubsub_service_agent
}

resource "google_pubsub_subscription_iam_member" "axon_dlq_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.axon_send_requested_sub.name
  role         = "roles/pubsub.subscriber"
  member       = local.pubsub_service_agent
}

# The lane axon-sender drains.
#
# max_delivery_attempts = 5, THE LEGAL MINIMUM, AND DELIBERATELY FAR BELOW BOTH
# DIS LANES (20 and 100). This will look like an oversight next to them, so:
#
#   THE DIS 100 IS EARNED BY A HUMAN PROCESS. Its comment records that the
#   ingress lane carries a documented self-heal where a message waits for a
#   catalogue or a position to onboard, which is sales uploading at 5pm and the
#   catalogue landing the next morning. ~16h covers same-working-day onboarding.
#
#   A SEND HAS NO ANALOGUE OF THAT. Its failures are a provider refusal, a bad
#   credential, or the database being unreachable, and none of them resolves by
#   waiting sixteen hours. Nothing is going to arrive that makes attempt 60
#   succeed where attempt 5 failed.
#
#   AND EVERY RETRY HERE HAS A COST THE DIS LANES DO NOT HAVE. The ledger write
#   is idempotent on delivery_id, but THE SEND IS NOT: a crash between the
#   provider's 202 and the ledger commit means the redelivery sends again. So
#   attempts are duplicate internal emails, and the budget is what bounds them.
#
# 5 attempts under the backoff below is roughly 20 minutes, which covers a Cloud
# SQL restart and a provider blip and then stops.
#
# retry_policy is a PREREQUISITE for max_delivery_attempts, not a nicety: delivery
# attempts are 1 + NACKs, so with no policy they accumulate at loop speed rather
# than wall-clock speed and a 60s database restart would burn the whole budget in
# seconds. The consumer also nacks plainly rather than with
# ack_deadline_seconds = 0, so this backoff is what actually governs the pace.
# A MAIN LANE, AND THE ONE THAT PROVED THE GAP. This subscription existed and was watched by no
# stuck-message alert, because that policy's filter had been hand-typed as
# "dis-(csv-received|ingress-ready)-sub" and nobody came back to it. A new one must also be added
# to main_subscription_names in the monitoring_alerts module call below. See csv_received_sub.
resource "google_pubsub_subscription" "axon_send_requested_sub" {
  project              = var.project_id
  name                 = "axon-send-requested-sub"
  topic                = google_pubsub_topic.axon_send_requested.id
  ack_deadline_seconds = 30

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.axon_send_requested_dlq.id
    max_delivery_attempts = 5
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  depends_on = [
    google_pubsub_topic_iam_member.axon_dlq_publisher,
  ]
}

module "axon_sender_service" {
  source = "../../modules/cloud-run-service-axon-sender"

  project_id       = var.project_id
  region           = var.region
  image            = var.axon_sender_image
  vpc_connector_id = module.network.vpc_connector_id

  # Referencing the subscription's attribute makes Terraform create the lane (and
  # its dead-letter IAM) before the service that drains it. A revision deployed
  # first would fail its startup check, which is the intended loud failure, but
  # the ordering makes it not happen at all.
  subscription_name = google_pubsub_subscription.axon_send_requested_sub.name

  alert_email = var.axon_platform_oncall_email
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

  # Square OAuth connect (S2). client id + redirect URL are per-env; the OAuth base URL
  # and the two secret names ride the module defaults (sandbox host, square-app-secret,
  # dis-ui-oauth-state-key). The app secret + state key are created out of band in
  # Secret Manager.
  square_client_id          = "sandbox-sq0idb-UNkdYKb0-JH_8P2vSsuBIg"
  square_oauth_redirect_uri = "https://dis-ui-ver2-697546531605.asia-south1.run.app/connectors/square/callback"

  # Clover OAuth connect (C3). The app secret rides the module default
  # (clover-app-secret, created out of band); the state key is shared with Square.
  # The redirect is the LAUNCH path, which is what is registered in the Clover dashboard.
  clover_client_id          = "T4RKJYVE63ARA"
  clover_oauth_redirect_uri = "https://dis-ui-ver2-697546531605.asia-south1.run.app/connectors/clover/launch"
  # SHARED with the clover-connector below - see var.clover_base_url. Both services stamp
  # `environment` onto the same token record from this host; one variable, one truth.
  clover_oauth_base_url = var.clover_base_url
}

# --- Wave 3: DIS Mirror Sync Cloud Run JOB ---
#
# The last piece of DIS that was still hand-seeded. Without it a tenant onboarded
# through CM gets no identity_mirror row and DIS falls back to showing a UUID; it
# also blocks tenant names in the DIS topbar and GET /api/v1/tenants-actable
# returning anything beyond hand-inserted rows.
#
# A run-to-completion JOB despite the name: one execution = one sync pass = exit,
# with a meaningful exit code. No scheduler - executions are manual, like the two
# connectors; the orchestration question is deferred.
#
# TWO ROLES, ONE DATABASE. Post-consolidation the CM read and the DIS write are the
# same instance and the same database (thalamus), separated by schema and role: the
# read is dis_mirror_reader on core.*, the write is ithina_dis_user on
# identity_mirror.*. That is why the module sets CM_DB_NAME and
# DIS_EXPECTED_DATABASE explicitly - both the service and dis-rls default to
# pre-consolidation database names that no longer exist.
module "mirror_sync_consumer_job" {
  source = "../../modules/cloud-run-job-mirror-sync-consumer"

  project_id       = var.project_id
  region           = var.region
  image            = var.mirror_sync_consumer_image
  vpc_connector_id = module.network.vpc_connector_id
}

# --- Synapse: the orchestrator job and its daily schedule ---
#
# THE FIRST SCHEDULED ANYTHING IN THIS PROJECT. Everything else here is invoked by a request, a
# Pub/Sub push, or an operator running `gcloud run jobs execute`. This module adds the Cloud
# Scheduler job that makes the Synapse shadow sweep happen without a human, plus the Cloud Run
# job it fires and the two identities involved.
#
# REQUIRES cloudscheduler.googleapis.com, added to infra/bootstrap's baseline in the same
# slice. Apply bootstrap first or this fails with SERVICE_DISABLED.
#
# STILL SHADOW ONLY: the sweep computes, appends to synapse.actions and synapse.run, and
# delivers nothing to anyone.
module "synapse_orchestrator" {
  source = "../../modules/cloud-run-job-synapse-orchestrator"

  project_id       = var.project_id
  region           = var.region
  image            = var.synapse_orchestrator_image
  vpc_connector_id = module.network.vpc_connector_id
}

# --- Wave 3: DIS UI SPA (dis-ui-ver2) Cloud Run service ---
#
# ADOPTED BY IMPORT, not created. dis-ui-ver2 has been serving from Cloud Run
# since before Terraform described it, so a clean-slate apply of this project
# used to produce no DIS UI at all. The module was written against the LIVE v2
# API config and imported; its acceptance test is a plan with no changes.
#
# COUPLED TO dis-ui-server ABOVE, in a way neither module shows on its own: the
# SPA's nginx reverse-proxies /api to dis-ui-server carrying only the browser's
# Auth0 bearer and NO credential of its own, so it works solely because
# dis-ui-server has an allUsers run.invoker binding. Tightening that posture
# breaks every /api call through this service with an immediate 403. The full
# explanation is the COUPLING block at the top of the module; read it before
# touching IAM in 2b-iii.
#
# The dis-ui-server block above already depends on this service's URL from the
# other direction (both OAuth redirect URIs point at it), so the two are wired
# together in both directions.
module "dis_ui_ver2_service" {
  source = "../../modules/cloud-run-service-dis-ui-ver2"

  project_id = var.project_id
  region     = var.region
  image      = var.dis_ui_ver2_image
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

# --- Wave 3: the Square connector, as a Cloud Run JOB ---
#
# One execution is one trigger: pull Square's catalog, write the CSV into bronze,
# publish ingress.ready. It feeds the SAME ingress.ready topic csv-ingest-worker
# publishes to, so streaming_consumer_service turns the result into canonical rows
# with no further wiring.
#
# The run target (tenant/store/source/template/run-key) is NOT here and not in the
# module: it is supplied per execution via `gcloud run jobs execute --args`. A
# multi-tenant connector's terraform must not know a tenant's ids, and a bare
# execute failing loudly on argparse (exit 2) is the intended behaviour.
#
# square_client_id must match the app id dis_ui_server_service connects with: the
# BFF mints the per-tenant token with that app, and the connector refreshes it with
# the same client_id + square-app-secret pair.

module "square_connector_job" {
  source = "../../modules/cloud-run-service-square-connector"

  project_id       = var.project_id
  region           = var.region
  image            = var.square_connector_image
  vpc_connector_id = module.network.vpc_connector_id

  # Referencing the inline resources makes Terraform create the bucket + topic
  # (and their IAM) before the job.
  bronze_bucket_name  = google_storage_bucket.dis_bronze.name
  ingress_topic_id    = google_pubsub_topic.ingress_ready.id
  ingress_ready_topic = google_pubsub_topic.ingress_ready.name

  # Same Square sandbox app as the BFF's connect flow. The OAuth/API host and the
  # two secret names ride the module defaults (sandbox host, dis-database-url,
  # square-app-secret).
  square_client_id = "sandbox-sq0idb-UNkdYKb0-JH_8P2vSsuBIg"
}

# --- Wave 3: the Clover connector, as a Cloud Run JOB (C4) ---
#
# One execution is one trigger: pull Clover's catalog, write the CSV into bronze,
# publish ingress.ready. It feeds the SAME ingress.ready topic csv-ingest-worker and
# the square-connector publish to, so streaming_consumer_service turns the result into
# canonical rows with no further wiring.
#
# The run target (tenant/store/source/template/run-key) is NOT here and not in the
# module: it is supplied per execution via `gcloud run jobs execute --args`.
#
# clover_client_id must match the app id dis_ui_server_service connects with: the BFF
# mints the per-tenant token with that app, and the connector refreshes it with the same
# client_id + clover-app-secret pair.

module "clover_connector_job" {
  source = "../../modules/cloud-run-service-clover-connector"

  project_id       = var.project_id
  region           = var.region
  image            = var.clover_connector_image
  vpc_connector_id = module.network.vpc_connector_id

  # Referencing the inline resources makes Terraform create the bucket + topic
  # (and their IAM) before the job.
  bronze_bucket_name  = google_storage_bucket.dis_bronze.name
  ingress_topic_id    = google_pubsub_topic.ingress_ready.id
  ingress_ready_topic = google_pubsub_topic.ingress_ready.name

  # Same Clover sandbox app as the BFF's connect flow, and the SAME host - see
  # var.clover_base_url for why the host is one variable rather than two.
  clover_client_id    = "T4RKJYVE63ARA"
  clover_api_base_url = var.clover_base_url
}

# --- Alerting, across DIS and Synapse ---
#
# THE FIRST OBSERVABILITY IN THIS PROJECT. Verified live before writing: 0 alert policies, 0
# notification channels, 0 log-based metrics. Six policies, one email channel, two log metrics.
#
# ONE MODULE FOR BOTH PLANES on purpose. Alerting per-component is how the dead-letter
# queues, the registry cleanup and Synapse's failed runs all ended up unobserved: each was
# somebody's concern and none was anybody's.
#
# NO NEW API IS REQUIRED. monitoring and logging were already enabled — by GCP's own defaults,
# not by this repository — and are now DECLARED in infra/bootstrap so a rebuilt project gets them
# and a plan would notice them being turned off.
#
# TWO OF THE SIX FIRE ON CREATION and that is the point rather than a defect: a message has been
# sitting in dis-ingress-ready-dlq for days, and The Body Shop's sale data is stale. Both were
# true and invisible before this module existed.
module "monitoring_alerts" {
  source = "../../modules/monitoring-alerts"

  project_id  = var.project_id
  alert_email = var.alert_email

  # Named rather than defaulted, so a rename of the job is a visible one-line change here instead
  # of six filters that silently match nothing.
  orchestrator_job_name = "synapse-orchestrator"

  # MUST TRACK synapse.orchestrator.freshness.STALE_AFTER_DAYS. Terraform cannot read a Python
  # constant, so this is a second source of truth kept in step by hand and named as such.
  stale_after_days = 3

  # EVERY MAIN LANE, BY REFERENCE. The stuck-message policy cannot use a wildcard the way the
  # dead-letter policy does: "every -sub that is not a DLQ" needs a negative lookahead and RE2
  # has none, so the mains have to be named. Naming them HERE, as resource references, is what
  # keeps a rename from silently un-matching the filter.
  #
  # ADDING A FOURTH MAIN SUBSCRIPTION MEANS ADDING IT HERE. Nothing enforces that; see the
  # comment at the subscription resources above.
  main_subscription_names = [
    google_pubsub_subscription.csv_received_sub.name,
    google_pubsub_subscription.ingress_ready_sub.name,
    google_pubsub_subscription.axon_send_requested_sub.name,
  ]
}

# --- migrate-synapse: the way Synapse's chain reaches this database ---
#
# NOT WIRED BEFORE NOW, and that absence was the finding: Synapse has had its own alembic chain
# with no mechanism to apply it. How 0001-0003 got here is recorded nowhere in this
# repository. Second instance of the same ledger item as DIS's missing migrate job.
#
# THE SAME IMAGE AS THE ORCHESTRATOR, by reference rather than a second pin, so the migration can
# never run a different build than the workload it migrates for.
#
# THE ADMIN SECRET MUST EXIST BEFORE THIS APPLIES. `synapse-admin-database-url` is created out of
# band like every other DSN secret here, and the ROLE IT HOLDS IS AN OPEN QUESTION — see the
# module's secret_admin_url description. Creating it against the wrong role leaves later
# migrations' objects owned differently from the tables they sit on.
module "migrate_synapse_job" {
  source = "../../modules/cloud-run-job-migrate-synapse"

  project_id       = var.project_id
  region           = var.region
  image            = var.synapse_orchestrator_image
  vpc_connector_id = module.network.vpc_connector_id
}

# --- migrate-axon: the way Axon's chain reaches this database ---
#
# SHIPPED WITH THE MODULE'S FIRST SLICE RATHER THAN AFTER IT, and that is the whole point. Both
# jobs above were written to close an absence that had already cost something: DIS's chain
# reached this database by hand for nineteen revisions, and how Synapse's first three arrived is
# recorded nowhere. Adding a third chain with no mechanism, to save copying a module, would make
# a standing HIGH finding true of one more plane.
#
# THE IMAGE IS THE BFF'S, not an Axon image, because Axon has none: it has no server of its own.
# synapse-ui-server's Dockerfile COPYs the whole axon/ directory, chain and DDL included, and
# this job runs alembic out of it with the CMD overridden.
#
# THE MANUAL PREREQUISITES ARE ORDERED AND THE ORDER BITES. CREATE ROLE axon_sender must happen
# BEFORE the first execution, because 0001 grants USAGE on the schema to it and a missing role
# fails the migration itself. Then this job. Then 06_axon_sender_grant.sql as the schema owner.
module "migrate_axon_job" {
  source = "../../modules/cloud-run-job-migrate-axon"

  project_id       = var.project_id
  region           = var.region
  image            = var.synapse_ui_server_image
  vpc_connector_id = module.network.vpc_connector_id
}

# --- migrate-dis: the way DIS's chain reaches this database ---
#
# THE SAME ABSENCE AS ABOVE, one plane over, and the older of the two. DIS's revisions reached
# this database BY HAND — infra/db-setup/README.md:45-49 records `postgres` at 18 revisions on
# 2026-07-20, while the live stamp is 0019, so at least one arrived later and unrecorded. This
# is the original `no-migrate-dis-job-exists` ledger item; migrate-synapse above was its second
# instance. Both now have a mechanism.
#
# THE FIRST EXECUTION APPLIES NOTHING. The database is already at head, so `upgrade head` is a
# no-op and the run proves the MECHANISM — image, identity, secret, VPC path, target guard,
# version table — exactly as migrate-synapse's first run did. Revision 0020 is the first that
# will reach staging without a proxy and a laptop.
#
# A DEDICATED IMAGE, not a workload's, and that is the one real divergence from both ancestors.
# migrate-cm rides cm-backend's image and migrate-synapse rides the orchestrator's because each
# of those already carried its chain. No DIS service image carries alembic at all — verified
# against the resolved closure of all four — and DIS's chain lives at the workspace root, owned
# by the root project that does declare it. The module header carries the full argument.
#
# POSTGRES_DB IS LOAD-BEARING HERE AND HAS NO ANALOGUE IN migrate-synapse. Eighteen of the
# nineteen revisions refuse to run unless it matches the connected database, and the code
# default is the local `ithina_dis_db`. Wired to var.database_name — the same variable the
# Cloud SQL module is given — rather than a literal, so the job and the database it targets
# cannot drift apart.
#
# THE ADMIN SECRET MUST EXIST BEFORE THIS APPLIES. `dis-admin-database-url` is created out of
# band like every other DSN secret here (done, 2026-08-07), against the `postgres` role —
# confirmed by uniform `postgres` ownership across all eight DIS schemas, not merely inferred
# from README:47.
module "migrate_dis_job" {
  source = "../../modules/cloud-run-job-migrate-dis"

  project_id        = var.project_id
  region            = var.region
  image             = var.dis_migrate_image
  vpc_connector_id  = module.network.vpc_connector_id
  expected_database = var.database_name
}
