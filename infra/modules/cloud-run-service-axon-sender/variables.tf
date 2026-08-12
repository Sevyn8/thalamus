###############################################################################
# cloud-run-service-axon-sender variables.
#
# axon-sender is Axon's poll loop over axon-send-requested, deployed as an
# always-on Cloud Run SERVICE on streaming-consumer's shape: min_instances = 1,
# cpu_idle = false, RUN_HEALTH_SERVER=true serving /healthz alongside the loop.
#
# IT PUBLISHES NOTHING and READS NOTHING. It holds one subscriber grant, one
# secret-backed DSN (axon_sender: INSERT on axon.platform_deliveries and no
# SELECT anywhere), and one secret-backed provider key. No invoker binding, no
# database read privilege, no topic.
###############################################################################

variable "project_id" {
  type        = string
  description = "GCP project id. Thalamus staging is sevyn8-thalamus-staging; never ithina-dis-cm."
}

variable "region" {
  type        = string
  description = "Region for the Cloud Run service (asia-south1 for Thalamus staging)."
}

variable "service_name" {
  type        = string
  description = "Cloud Run v2 service name."
  default     = "axon-sender"
}

variable "service_account_id" {
  type        = string
  description = "Runtime service account id. Its own SA, not the default compute identity: that one is a standing HIGH finding and a new service is the cheapest moment not to inherit it."
  default     = "axon-sender-run"
}

variable "image" {
  type        = string
  description = "Container image, explicit tag and never a floating `latest`. Built from axon/services/axon-sender with the MONOREPO ROOT as build context: the service is a uv workspace member alongside thalamus-axon, so a dis/-rooted context cannot reach it."
}

variable "vpc_connector_id" {
  type        = string
  description = "Serverless VPC connector id. Cloud SQL is private-IP only, so the loop reaches it through the connector; SendGrid is public and leaves over the default internet path under PRIVATE_RANGES_ONLY egress."
}

variable "subscription_name" {
  type        = string
  description = "The subscription this service drains. Passed in rather than constructed so Terraform sees an edge from the service to the lane and creates the lane first; the service's own startup check fails loud if it is absent."
}

variable "secret_sender_url" {
  type        = string
  description = "Secret Manager id of the axon_sender DSN. INSERT on axon.platform_deliveries and NOTHING else: no SELECT anywhere, nothing on axon.tenant_deliveries. Grants come from infra/db-setup/sql/06_axon_sender_grant.sql. The service refuses to start without it."
  default     = "axon-sender-database-url"
}

variable "secret_sendgrid_api_key" {
  type        = string
  description = "Secret Manager id of Sevyn8's own SendGrid key, for Sevyn8's own internal traffic. NOT a tenant credential: tenant traffic is sent by the TENANT under its own account, and none of that exists yet."
  default     = "axon-sendgrid-api-key"
}

variable "sendgrid_from_email" {
  type        = string
  description = "AXON_SENDGRID_FROM_EMAIL. It MUST be a SendGrid-VERIFIED sender on the account: SendGrid refuses an unverified sender per message, at runtime, which reads like a provider outage rather than a configuration error. Not a secret, so a plain variable."
  default     = "noreply@sevyn8.com"

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.sendgrid_from_email))
    error_message = "sendgrid_from_email must be a single email address."
  }
}

variable "alert_email" {
  type        = string
  description = "Unused by the container and present so the module's caller passes the same address the rest of the delivery plane uses, keeping one source of truth for who is on call. Reserved for a future per-service notification channel."
  default     = ""
}

variable "expected_database" {
  type        = string
  description = "DIS_EXPECTED_DATABASE. dis-rls refuses any database but this one, defaulting to the pre-consolidation ithina_dis_db which no longer exists, so it is set explicitly as every service here does."
  default     = "thalamus"
}

variable "min_instances" {
  type        = number
  description = "ONE, AND THIS IS LOAD-BEARING. A queue is drained continuously or it is a backlog. At zero the loop scales away and messages sit until something else wakes the service, which nothing does: there is no inbound request to trigger a cold start, because the work is entirely an outbound pull."
  default     = 1
}

variable "max_instances" {
  type        = number
  description = "Concurrency ceiling. The consumer is safe to run at more than one instance: the ledger write is idempotent on delivery_id (pk_platform_deliveries), so two instances racing the same redelivered message produce one row and one duplicate-ack. Kept at 1 anyway because the volume is a handful of messages a day and a second instance would only widen the duplicate-send window."
  default     = 1
}

variable "cpu" {
  type        = string
  description = "CPU limit."
  default     = "1"
}

variable "memory" {
  type        = string
  description = "Memory limit."
  default     = "512Mi"
}
