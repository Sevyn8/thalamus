variable "project_id" {
  type        = string
  description = "The project the policies, metrics and channel live in."
}

variable "alert_email" {
  type        = string
  description = <<-EOT
    Destination for every alert in this module. A LIST, NOT A PERSON: a personal address breaks
    when one of three people is away, and needs changing when the team grows.

    NOT DEFAULTED, deliberately. A default would let this module apply with a plausible-looking
    address that nobody reads, which is the artifact class this project keeps deleting — an alert
    nobody reads is a log nobody greps.

    Cloud Identity API is not enabled on this project, so which groups exist could not be
    enumerated from the CLI (`gcloud identity groups describe` fails with API not enabled).
    Confirm the list exists and accepts external senders before relying on this.
  EOT

  validation {
    condition     = can(regex("^[^@]+@[^@]+\\.[^@]+$", var.alert_email))
    error_message = "alert_email must be a single email address."
  }

  validation {
    # A weak but real guard against the failure this module exists to avoid.
    condition     = !can(regex("(?i)(example|test|changeme|todo|invalid)", var.alert_email))
    error_message = "alert_email looks like a placeholder. An alert nobody reads is worse than none."
  }
}

variable "orchestrator_job_name" {
  type        = string
  description = "Cloud Run job name for the Synapse orchestrator. Used in metric filters; a typo here makes every Synapse policy silently never fire."
  default     = "synapse-orchestrator"
}

variable "stale_after_days" {
  type        = number
  description = <<-EOT
    Sale-data age, in days, above which a tenant is stale. MUST MATCH
    synapse.orchestrator.freshness.STALE_AFTER_DAYS — two sources of truth for one threshold, kept
    in step by hand because Terraform cannot read a Python constant. If they drift, the alert and
    the log line disagree about the same word.
  EOT
  default     = 3
}

variable "stuck_message_age_seconds" {
  type        = number
  description = "Oldest-unacked age on a MAIN subscription above which messages are considered stuck. Covers a dead consumer and a nack loop with one number."
  default     = 3600
}

variable "orchestrator_silence_seconds" {
  type        = number
  description = <<-EOT
    How long without a completed execution before the orchestrator is considered to have stopped
    running. Default 93600s = 26h: one daily cadence plus two hours of slack, so a late run does
    not page and a missed day does.
  EOT
  default     = 93600
}
