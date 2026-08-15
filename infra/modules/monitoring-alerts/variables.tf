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

variable "main_subscription_names" {
  type        = list(string)
  description = <<-EOT
    Every MAIN Pub/Sub subscription, by name, that the stuck-message policy should watch. Passed
    from the env as RESOURCE REFERENCES rather than literals, so a rename follows the reference
    instead of silently un-matching a hand-typed regex.

    Dead-letter subscriptions must NOT appear here. A DLQ holds old messages by design, so one in
    this list would alert permanently and teach the operator to ignore the policy.
  EOT

  validation {
    condition     = length(var.main_subscription_names) > 0
    error_message = "The stuck-message alert would be created watching no subscriptions at all: an empty list joins to an empty regex, which matches nothing, applies cleanly, and reports healthy for ever."
  }

  validation {
    condition     = length([for n in var.main_subscription_names : n if endswith(n, "-dlq-sub")]) == 0
    error_message = "A dead-letter subscription is in the main list. It would breach the oldest-unacked threshold permanently, because holding old messages is what a DLQ is for, and a policy that is always red is a policy nobody reads."
  }
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
