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
  description = "Account id for this service's DEDICATED runtime identity. Holds secretAccessor on THREE secrets: the synapse_reader DSN, the synapse_lifecycle DSN (slice 5d) and the synapse_provisioner DSN (slice 5e). NOT the writer, which is the orchestrator's identity and holds INSERT on synapse.actions. Each write credential is one verb on one table: lifecycle appends to synapse.action_events so the console can record a snooze, dismissal or acknowledgement, and provisioner inserts into synapse.provision so the console can enable a monitor. Neither can UPDATE anything, so neither can edit or undo what it wrote."
  default     = "synapse-ui-server"
}

variable "caller_service_account_email" {
  type        = string
  description = "The identity permitted to invoke this service. Today this is the project's DEFAULT COMPUTE service account, because cm-frontend has no dedicated one — so the binding admits every default-compute workload in the project, not cm-frontend alone. It removes ANONYMOUS access, which is the substance of the standing HIGH finding, and nothing more. See the module header."
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
  description = "Secret Manager id of the synapse_lifecycle DSN. INSERT on synapse.action_events and nothing else. Arrived with slice 5d; the service refuses to start without it."
  default     = "synapse-lifecycle-database-url"
}

variable "secret_provisioner_url" {
  type        = string
  description = "Secret Manager id of the synapse_provisioner DSN. INSERT on synapse.provision, plus SELECT on identity_mirror.tenants and canonical.store_sku_current_position because the enablement pre-flight runs in the same transaction as the insert and cannot execute without them. No UPDATE, so the console can enable a monitor and cannot disable one or edit a timezone. Not synapse_writer and not synapse_lifecycle. Created OUT OF BAND like the other two DSN secrets; grants come from infra/db-setup/sql/05_synapse_provisioner_grant.sql. Arrived with slice 5e; the service refuses to start without it."
  default     = "synapse-provisioner-database-url"
}

variable "secret_axon_sender_url" {
  type        = string
  description = "Secret Manager id of the axon_sender DSN (Axon slice 1). INSERT on axon.platform_deliveries and NOTHING else: no SELECT anywhere, nothing at all on axon.tenant_deliveries. The absence of SELECT is why the send path mints its own UUIDv7 and uses neither RETURNING nor ON CONFLICT, both of which need it. Created OUT OF BAND like the three Synapse DSNs; grants come from infra/db-setup/sql/06_axon_sender_grant.sql. The service refuses to start without it."
  default     = "axon-sender-database-url"
}

variable "secret_axon_reader_url" {
  type        = string
  description = "Secret Manager id of the axon_reader DSN (Axon slice 3). SELECT on axon.platform_deliveries and axon.tenant_deliveries, and NO write verb anywhere. NOT the sender's DSN and not a widening of it: axon_sender deliberately holds no SELECT, so reusing it would let the send path read back the ledger of who was contacted about what. Created OUT OF BAND like every other DSN here; grants come from infra/db-setup/sql/07_axon_reader_grant.sql. The service refuses to start without it."
  default     = "axon-reader-database-url"
}

variable "secret_axon_sendgrid_api_key" {
  type        = string
  description = "Secret Manager id of SEVYN8'S OWN SendGrid API key (Axon slice 1). NOT a tenant credential: for tenant traffic the TENANT is the sender, under its own WhatsApp Business account, its own DLT registration and its own credentials, and none of that exists yet. A SEPARATE secret from cm-sendgrid-api-key rather than a shared grant on CM's: a secret named for one module and read by another is a name that lies, and a separately revocable key means an Axon compromise does not force a rotation of Customer Master's invitation flow. Created OUT OF BAND."
  default     = "axon-sendgrid-api-key"
}

variable "axon_sendgrid_from_email" {
  type        = string
  description = "AXON_SENDGRID_FROM_EMAIL - the from-address on Sevyn8's own outbound mail. It MUST be a SendGrid-VERIFIED sender on the account: SendGrid refuses an unverified sender per message, at runtime, which reads like a provider outage rather than a configuration error. Not a secret, so it is a plain variable rather than a Secret Manager reference."
  default     = "noreply@sevyn8.com"

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.axon_sendgrid_from_email))
    error_message = "axon_sendgrid_from_email must be a single email address."
  }
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
