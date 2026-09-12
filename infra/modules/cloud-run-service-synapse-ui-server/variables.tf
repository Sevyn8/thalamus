variable "project_id" {
  type        = string
  description = "The Thalamus GCP project id."
}

variable "region" {
  type        = string
  description = "Region for the Cloud Run service."
  default     = "asia-south1"
}

variable "service_name" {
  type        = string
  description = "Cloud Run service name. Also the audience cm-frontend mints its ID token for."
  default     = "synapse-ui-server"
}

variable "image" {
  type        = string
  description = "Fully-qualified image pinned to an explicit vN tag. Never :latest — a floating tag is how thalamus-images/dis-ui-ver2:latest came to point at v7 while v15 was serving."
}

variable "service_account_id" {
  type        = string
  description = "Account id for this service's DEDICATED runtime identity. Holds secretAccessor on THREE secrets: the synapse_reader DSN, the synapse_lifecycle DSN and the synapse_provisioner DSN. NOT the writer, which is the orchestrator's identity and holds INSERT on synapse.actions. Each write credential is one verb on one table: lifecycle appends to synapse.action_events so the console can record a snooze, dismissal or acknowledgement, and provisioner inserts into synapse.provision so the console can enable a monitor. Neither can UPDATE anything, so neither can edit or undo what it wrote."
  default     = "synapse-ui-server"
}

variable "caller_service_account_email" {
  type        = string
  description = "The identity permitted to invoke this service: cm-frontend's DEDICATED runtime account (P1-IAM-001A). Created at the staging root, not in cm-frontend's module, because that module already depends on this one and owning the account there would make the two modules reference each other. This binding is the target posture and survives P1-IAM-001B."

  validation {
    condition     = !can(regex("-compute@developer\\.gserviceaccount\\.com$", var.caller_service_account_email))
    error_message = "The dedicated Synapse caller must not be a default Compute Engine service account - that binding admits every default-compute workload in the project. The legacy member has its own variable (legacy_caller_service_account_email) so it stays visible and dated."
  }
}

variable "legacy_caller_service_account_email" {
  type        = string
  description = "TEMPORARY P1-IAM-001A MIGRATION COMPATIBILITY. REMOVE IN P1-IAM-001B AFTER LIVE CM FRONTEND VERIFICATION. The project's DEFAULT COMPUTE service account, which the currently-serving cm-frontend revision runs as. Retained only so that revision keeps invoker until a revision running as the dedicated identity has been proven live; dropping it in the same apply that rolls the new revision would refuse the serving one before its replacement is ready. This variable exists SEPARATELY, and is named for what it is, so the broad member cannot hide behind a generic name."
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC Access connector. Cloud SQL is reached over the private IP through this, which is why the service needs no roles/cloudsql.client."
}

variable "secret_reader_url" {
  type        = string
  description = "Secret Manager id of the synapse_reader DSN. Read-only on two canonical tables plus synapse.actions, provision and run."
  default     = "synapse-reader-database-url"
}

variable "secret_lifecycle_url" {
  type        = string
  description = "Secret Manager id of the synapse_lifecycle DSN. INSERT on synapse.action_events and nothing else. The service refuses to start without it."
  default     = "synapse-lifecycle-database-url"
}

variable "secret_provisioner_url" {
  type        = string
  description = "Secret Manager id of the synapse_provisioner DSN. INSERT on synapse.provision, plus SELECT on identity_mirror.tenants and canonical.store_sku_current_position because the enablement pre-flight runs in the same transaction as the insert and cannot execute without them. No UPDATE, so the console can enable a monitor and cannot disable one or edit a timezone. Not synapse_writer and not synapse_lifecycle. Created OUT OF BAND like the other two DSN secrets; grants come from infra/db-setup/sql/05_synapse_provisioner_grant.sql. The service refuses to start without it."
  default     = "synapse-provisioner-database-url"
}

variable "secret_axon_reader_url" {
  type        = string
  description = "Secret Manager id of the axon_reader DSN. SELECT on axon.platform_deliveries and axon.tenant_deliveries, and NO write verb anywhere. NOT the sender's DSN and not a widening of it: axon_sender deliberately holds no SELECT, so reusing it would let the send path read back the ledger of who was contacted about what. Created OUT OF BAND like every other DSN here; grants come from infra/db-setup/sql/07_axon_reader_grant.sql. The service refuses to start without it."
  default     = "axon-reader-database-url"
}

variable "axon_send_topic" {
  type        = string
  description = "The axon-send-requested topic this service publishes to. Passed in rather than constructed so Terraform sees an edge from the service to the topic and creates the topic first, and so the publisher grant is TOPIC-SCOPED rather than project-wide."
}

variable "axon_platform_oncall_email" {
  type        = string
  description = <<-EOT
    AXON_PLATFORM_ONCALL_EMAIL - where Axon delivers internal platform events.

    A LIST, NOT A PERSON: a personal address breaks when one of three people is away, and needs
    changing when the team grows. Same argument as monitoring-alerts' alert_email.

    DELIBERATELY NOT THE SAME VARIABLE as that module's. monitoring-alerts carries facts about
    PROCESSES (a job died, a queue is stuck) and it is Cloud Monitoring that both detects and
    sends, which is what keeps it outside the system it watches. Axon carries facts about the
    DOMAIN. Wiring one to the other would make the alert that Axon is down be delivered by Axon.
    The two may resolve to the same inbox; they must not resolve to the same variable.

    NOT DEFAULTED, deliberately, for the reason monitoring-alerts states: a default would let this
    apply with a plausible-looking address nobody reads.
  EOT

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.axon_platform_oncall_email))
    error_message = "axon_platform_oncall_email must be a single email address."
  }

  validation {
    condition     = !can(regex("(?i)(example|test|changeme|todo|invalid)", var.axon_platform_oncall_email))
    error_message = "axon_platform_oncall_email looks like a placeholder. A delivery nobody reads is worse than none."
  }
}

variable "cm_api_base_url" {
  type        = string
  description = "CM_API_BASE_URL - Customer Master's origin, called SERVER-SIDE by the provisioning gate. Provisioning is authorized by asking CM's /api/v1/me/can-do whether the caller holds ADMIN.TENANTS.CONFIGURE.GLOBAL, forwarding the caller's own Auth0 token; the gate denies on any failure including a CM outage. Synapse defines no permission of its own and holds no copy of CM's model. Pass module.cm_service.service_url by reference rather than a copied literal, so the two cannot drift. No trailing slash: config.py strips one anyway, because a doubled slash produces a 404 that reads like a missing endpoint. The service refuses to start without it, because a service that cannot evaluate its own authorization must not serve the route."
}

variable "dis_expected_database" {
  type        = string
  description = "The database dis-rls will accept. Must be the consolidated `thalamus`; its own default is the pre-consolidation ithina_dis_db, which no longer exists."
  default     = "thalamus"
}

variable "jwt_issuer" {
  type        = string
  description = "Auth0 issuer URL. The JWKS URL is DERIVED from it in config.py rather than configured separately: a JWKS URL disagreeing with the issuer verifies tokens from the wrong directory."
}

variable "jwt_audience" {
  type        = string
  description = "The API identifier this service accepts tokens for."
}

variable "min_instances" {
  type        = number
  description = "Zero. A superadmin console is used occasionally; a cold start is cheaper than a warm instance holding a database pool open all night."
  default     = 0
}

variable "max_instances" {
  type        = number
  description = "Bounded because every request opens a Cloud SQL connection through the reader role."
  default     = 4
}

variable "cpu" {
  type        = string
  default     = "1"
  description = "The work is IO-bound on Postgres, not compute-bound."
}

variable "memory" {
  type        = string
  default     = "512Mi"
  description = "Reads are aggregated in SQL and bounded at 500 rows; nothing large is held in memory."
}

variable "client" {
  type        = string
  default     = "terraform"
  description = "Declared because it is Optional and NOT Computed in the provider: undeclared, it diffs on every plan forever."
}

variable "client_version" {
  type        = string
  default     = ""
  description = "See `client`."
}
