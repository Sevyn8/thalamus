# =============================================================================
# ALERTING, ACROSS DIS AND SYNAPSE. Six policies, one channel, two log metrics.
# =============================================================================
#
# ONE MODULE COVERING BOTH PLANES, deliberately. Alerting per-component is how three mechanisms
# ended up unobserved in the first place: each was somebody's job and none was anybody's.
#
# WHAT WAS HERE BEFORE THIS FILE: nothing. Verified live on 2026-08-05 rather than assumed —
# 0 alert policies, 0 notification channels, 0 log-based metrics in the project. The
# monitoring and logging APIs were enabled only because GCP auto-enables them; they are now
# declared in infra/bootstrap.
#
# =============================================================================
# WHY THERE ARE SIX AND NOT SIXTEEN
# =============================================================================
# An alerting system that fires on everything trains people to ignore it, and that is worse than
# no alerting because it LOOKS like coverage. So the exclusions were measured, not asserted.
#
#   A BLANKET `severity>=ERROR` POLICY WOULD HAVE FIRED 28 TIMES ON DAY ONE.
#
# Measured over 14 days to 2026-08-05: 246 entries in run.googleapis.com/stderr, 95 in
# cloudsql.googleapis.com/postgres.log, 45 in run.googleapis.com/requests, ~13 cloudaudit —
# streaming-consumer 141, csv-ingest-worker 88, synapse-ui-server 27, dis-ui-server 16.
# That sentence is here so that the next person tempted to add a catch-all policy has the number
# in front of them. The fix for 28 errors a day is to fix the errors, not to page on them.
#
# DELIBERATELY NOT ALERTED, and each for a stated reason:
#   - Generic service ERROR / 5xx volume. See the number above.
#   - cloudsql postgres.log errors. Mostly the identity_mirror grant gap; a dashboard concern.
#   - Artifact Registry cleanup. The live policy deletes UNTAGGED only (90d) and keeps ALL
#     TAGGED; every deployed image is pinned by tag. A weekly look, not a page.
#   - cm-backend / cm-frontend / dis-ui. Interactive surfaces, no customers: a human notices
#     faster than an email would.
#   - `blocked` / `undeclared` outcomes. Those are CORRECT refusals. Alerting on correctness
#     trains exactly the wrong reflex.
#   - A `WARNING` takeover line. It means recovery WORKED.
#   - Connector and mirror-sync silence. They are Cloud Run JOBS WITH NO SCHEDULER — executions
#     are operator-run (see cloud-run-service-square-connector/main.tf:264), so there is no
#     cadence to violate and an absence alert would fire permanently. The real failure — data
#     stopped arriving — is covered by the tenant-freshness policy below, which is why that one
#     alert replaces two that were originally asked for.
#
# =============================================================================
# THE TWO SETTINGS THAT MAKE A POLICY SILENTLY NEVER FIRE
# =============================================================================
# Both are called out at their use sites, because this is the failure mode of the whole session:
#
#   1. evaluation_missing_data. A counter with no series yet (nothing has ever failed, so
#      `result="failed"` does not exist) behaves differently from a gauge that stopped being
#      written. The two cases want OPPOSITE settings and both are set explicitly below.
#   2. logName scoping. The orchestrator's only ERROR-severity entry today is a
#      cloudaudit/system_event, not an application log. A filter on job_name alone would match
#      audit noise and report it as a failed slot.

# -----------------------------------------------------------------------------
# Where alerts go
# -----------------------------------------------------------------------------
#
# EMAIL, NOT PAGERDUTY. Sevyn8 is three people and nobody is on call; paging a rotation that does
# not exist is theatre. Email is free, terraform-native, and needs no secret — a Slack webhook URL
# would be a credential in state for no gain over a list that is already read.
resource "google_monitoring_notification_channel" "email" {
  project      = var.project_id
  display_name = "Thalamus alerts (${var.alert_email})"
  type         = "email"
  description  = "Every policy in modules/monitoring-alerts notifies here. One channel, on purpose: six alerts do not need routing, and routing is how an alert ends up going nowhere."

  labels = {
    email_address = var.alert_email
  }
}

# -----------------------------------------------------------------------------
# Log-based metric 1: a slot that FAILED inside a sweep
# -----------------------------------------------------------------------------
#
# FILTERED ON THE OUTCOME FIELD, NOT ON SEVERITY. `jsonPayload.outcome="failed"` is what makes
# this precisely a failed slot. A bare `severity>=ERROR` filter would also match "the sweep could
# not start" (a different failure, with a different action, already covered by the execution-count
# policy) and the cloudaudit system_event that is the job's only ERROR entry today.
#
# THE FIELD PATH IS FLAT, and that was verified by running the logger rather than reading it:
# dis_core.logging uses pythonjsonlogger with rename_fields levelname->severity, and `extra`
# lands at the TOP LEVEL of jsonPayload. Confirmed emitted shape:
#   {"asctime":...,"severity":"ERROR","name":...,"message":...,"outcome":"failed","tenant_id":...}
# A nested path (jsonPayload.extra.outcome) would extract nothing, forever, while looking correct.
resource "google_logging_metric" "synapse_slot_failed" {
  project = var.project_id
  name    = "synapse/slot_failed"

  filter = <<-EOT
    resource.type="cloud_run_job"
    resource.labels.job_name="${var.orchestrator_job_name}"
    logName="projects/${var.project_id}/logs/run.googleapis.com%2Fstderr"
    jsonPayload.outcome="failed"
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "INT64"
    unit         = "1"
    display_name = "Synapse slots that failed"

    labels {
      key         = "analysis_id"
      value_type  = "STRING"
      description = "Which analysis failed, so the alert can name the pair."
    }
    labels {
      key         = "tenant_id"
      value_type  = "STRING"
      description = "Which tenant."
    }
  }

  label_extractors = {
    analysis_id = "EXTRACT(jsonPayload.analysis_id)"
    tenant_id   = "EXTRACT(jsonPayload.tenant_id)"
  }
}

# -----------------------------------------------------------------------------
# Log-based metric 2: per-tenant sale-data age
# -----------------------------------------------------------------------------
#
# THIS IS THE ABSENCE FAILURE TURNED INTO A NUMBER. A tenant whose data stopped arriving produces
# runs that SUCCEED daily for ever — `satisfied` means every capability RESOLVED, not that
# anything was found — so no execution-status signal can see it. synapse.orchestrator.freshness
# emits the age of the newest sale for EVERY swept tenant on EVERY sweep, healthy ones included,
# because a signal that is absent when things are good cannot be thresholded.
#
# A DISTRIBUTION, so the policy can alert on the MAX across tenants while the metric keeps one
# series per tenant via the label. A plain counter would count log lines, not measure age.
#
# NO SEVERITY IN THE FILTER: the emitter uses WARNING when stale and INFO when fresh, and this
# metric must capture BOTH or the healthy-day series disappears and the threshold has nothing to
# compare against.
resource "google_logging_metric" "synapse_sale_age_days" {
  project = var.project_id
  name    = "synapse/tenant_sale_age_days"

  filter = <<-EOT
    resource.type="cloud_run_job"
    resource.labels.job_name="${var.orchestrator_job_name}"
    logName="projects/${var.project_id}/logs/run.googleapis.com%2Fstderr"
    jsonPayload.sale_age_days!=""
  EOT

  metric_descriptor {
    metric_kind  = "DELTA"
    value_type   = "DISTRIBUTION"
    unit         = "d"
    display_name = "Age of the newest sale, per tenant"

    labels {
      key         = "tenant_id"
      value_type  = "STRING"
      description = "Which tenant, so the alert names one rather than saying 'a tenant'."
    }
    labels {
      key         = "ever_sold"
      value_type  = "STRING"
      description = "false when the tenant has NEVER sent a sale — a different problem from having stopped."
    }
  }

  value_extractor = "EXTRACT(jsonPayload.sale_age_days)"

  label_extractors = {
    tenant_id = "EXTRACT(jsonPayload.tenant_id)"
    ever_sold = "EXTRACT(jsonPayload.ever_sold)"
  }

  # Days, not milliseconds. 1,2,4,...~1024 days covers "yesterday" through "over two years",
  # which is the whole useful range for a staleness measure.
  bucket_options {
    exponential_buckets {
      num_finite_buckets = 11
      growth_factor      = 2
      scale              = 1
    }
  }
}

# =============================================================================
# THE SIX POLICIES
# =============================================================================
#
# EVERY documentation BLOCK NAMES WHAT TO DO, not just what happened (D3). "synapse orchestrator
# failed" is a fact; "a slot failed and will never retry, so it needs a manual re-run" is an
# instruction. The person reading these at 2am did not write them.

# --- 1. A dead-letter queue is not empty ------------------------------------
#
# THIS ONE IS TRUE THE MOMENT IT IS CREATED. dis-ingress-ready-dlq-sub held one message on
# 2026-08-05, 5.4 days old, which is proof the alert is needed rather than a reason to soften it.
resource "google_monitoring_alert_policy" "dlq_not_empty" {
  project      = var.project_id
  display_name = "A dead-letter queue is not empty"
  combiner     = "OR"

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **A message has exhausted every delivery attempt and been dead-lettered. It is being kept,
      not retried. Nothing will pick it up.**

      WHAT TO DO:

      1. Read it WITHOUT acking — `gcloud pubsub subscriptions pull <sub> --limit=1` does not ack
         unless you pass `--auto-ack`. The message is the only evidence of whatever failed.
      2. `CloudPubSubDeadLetterSourceDeliveryCount` tells you how many times it was retried, and
         `CloudPubSubDeadLetterSourceSubscription` which consumer rejected it.
      3. Find the cause by `jsonPayload.trace_id` from the message body. A DETERMINISTIC failure
         (a parse error, a contract violation) will never succeed on retry — replaying it
         unchanged just repeats the loop.
      4. Fix the cause, then replay. Do NOT ack to clear the alert: acking discards the evidence
         and the data.

      **RETENTION IS 31 DAYS AND THEN IT IS GONE.** These subscriptions set
      `message_retention_duration = 2678400s` and `expiration_policy ttl = ""`, so the
      subscription never expires but the message does. There is no second copy.

      Known instance: a Body Shop CSV ingested 2026-07-30 failed date parsing
      (`source_sale_timestamp` — polars `strptime` with no usable format), nacked 100 times over
      ~12 hours, and dead-lettered on 07-31. It is the direct cause of that tenant's sale data
      being stale, which the tenant-freshness alert reports separately.
    EOT
  }

  conditions {
    display_name = "undelivered messages in a *-dlq-sub"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\"",
        "resource.type=\"pubsub_subscription\"",
        "resource.label.subscription_id=monitoring.regex.full_match(\"dis-.*-dlq-sub\")",
      ])

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      # Five minutes, not zero: a message in flight to a DLQ can register transiently.
      duration = "300s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MAX"
        # Per subscription, so the alert names WHICH queue.
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["resource.label.subscription_id"]
      }

      # A DLQ with no messages still reports 0 — the series always exists. So missing data here
      # means the metric pipeline broke, not that the queue is empty, and treating it as "fine"
      # would be the silent-never-fires failure.
      evaluation_missing_data = "EVALUATION_MISSING_DATA_INACTIVE"
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]

  # A dead-lettered message persists until someone acts. Without a rate limit this re-notifies
  # every evaluation for up to 31 days, which is how an alert becomes wallpaper.
  alert_strategy {
    notification_rate_limit {
      period = "86400s"
    }
  }
}

# --- 2. The orchestrator's execution FAILED ---------------------------------
#
# NOT MERGED WITH #3, and the reason is the action. A crashed execution and a failed slot inside a
# healthy execution need different things done: this one means the process died and the whole
# sweep may not have run; #3 means the sweep ran and one pair is permanently unfinished.
resource "google_monitoring_alert_policy" "orchestrator_execution_failed" {
  project      = var.project_id
  display_name = "Synapse orchestrator: the execution failed"
  combiner     = "OR"

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **The orchestrator job exited non-zero. The sweep did not complete, so some or all
      provisioned pairs did not run at all today.**

      WHAT TO DO:

      1. `gcloud run jobs executions list --job=${var.orchestrator_job_name} --region=asia-south1`
         then `describe` the failed one.
      2. Exit code 2 means the sweep could not START — look for `the sweep could not start` in the
         logs. That is configuration or connectivity (a DSN, a grant, RLS), not analysis.
      3. Re-run by hand once fixed: `gcloud run jobs execute ${var.orchestrator_job_name}
         --region=asia-south1`. A slot already finished is skipped, so a re-run is safe and
         idempotent — it will not duplicate actions.
      4. `max_retries = 1`, so Cloud Run already retried once. A second failure is not transient.

      NOTE: a run that ends `blocked` or `undeclared` is a CORRECT refusal and does not reach
      here — those are outcomes, not failures.
    EOT
  }

  conditions {
    display_name = "a completed execution with result=failed"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
        "resource.type=\"cloud_run_job\"",
        "resource.label.job_name=\"${var.orchestrator_job_name}\"",
        "metric.label.result=\"failed\"",
      ])

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "600s"
        per_series_aligner = "ALIGN_DELTA"
      }

      # CRITICAL, AND THE OPPOSITE OF THE FRESHNESS POLICY'S SETTING. Nothing has ever failed, so
      # the `result="failed"` series DOES NOT EXIST yet — verified live: only `result="succeeded"`
      # series are present for all five jobs. If missing data were treated as a breach this policy
      # would fire immediately and permanently on a system where nothing is wrong.
      evaluation_missing_data = "EVALUATION_MISSING_DATA_INACTIVE"
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
}

# --- 3. A slot FAILED inside a sweep that succeeded -------------------------
#
# THE IMPORTANT ONE. `failed` is TERMINAL: claim() skips a slot that already has a row, and
# tomorrow is a different slot, so nothing retries this — ever — without a person.
resource "google_monitoring_alert_policy" "synapse_slot_failed" {
  project      = var.project_id
  display_name = "Synapse: a slot failed and will never retry"
  combiner     = "OR"

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **One (tenant, analysis, slot) failed. The execution itself succeeded, so no execution-status
      signal shows this. NOTHING WILL RETRY IT.**

      Why it is terminal: `failed` is written to `synapse.run` for that slot. `claim()` skips a
      slot that already has a row, and tomorrow's sweep is a DIFFERENT slot. So the day is lost
      until a person re-runs it — this is not a transient condition that resolves itself.

      WHAT TO DO:

      1. Find the pair: the alert labels carry `analysis_id` and `tenant_id`. The log line has
         `jsonPayload.slot` and `jsonPayload.detail`.
      2. Fix the cause.
      3. Re-run THAT PAIR:
         `gcloud run jobs execute ${var.orchestrator_job_name} --region=asia-south1 --args=--tenant=<TENANT>,--analysis=<ANALYSIS>,--now=<SLOT>T12:00:00Z`
         Use `--dry-run` first: it resolves, evaluates and proposes while writing nothing.
      4. A re-run for a slot whose row says `failed` is the case this alert exists to prompt. Note
         it will need the existing row dealt with — `claim()` will skip it otherwise.

      A `WARNING` line reading "took over a crashed attempt" is the SUCCESS case of the same
      machinery and is deliberately not alerted.
    EOT
  }

  conditions {
    display_name = "a run row with outcome=failed"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"logging.googleapis.com/user/${google_logging_metric.synapse_slot_failed.name}\"",
        "resource.type=\"cloud_run_job\"",
      ])

      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period     = "600s"
        per_series_aligner   = "ALIGN_DELTA"
        cross_series_reducer = "REDUCE_SUM"
        group_by_fields      = ["metric.label.analysis_id", "metric.label.tenant_id"]
      }

      # A log-based counter has no series until the first matching line. Same reasoning as #2.
      evaluation_missing_data = "EVALUATION_MISSING_DATA_INACTIVE"
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
}

# --- 4. The orchestrator did not run ---------------------------------------
#
# THE ABSENCE PRIMITIVE. condition_absent is the only one of the six that alerts on nothing
# happening, and it is native — no code, no exporter, no custom metric.
resource "google_monitoring_alert_policy" "orchestrator_did_not_run" {
  project      = var.project_id
  display_name = "Synapse orchestrator: no execution in 26 hours"
  combiner     = "OR"

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **The orchestrator has not completed an execution in ${var.orchestrator_silence_seconds / 3600}
      hours. It runs daily. Nothing analysed anything yesterday, and no failure was reported
      because nothing ran to fail.**

      This is the failure that has no error message. Everything is green because everything is
      absent.

      WHAT TO DO — check in this order, outermost first:

      1. The schedule: `gcloud scheduler jobs describe synapse-orchestrator-daily
         --location=asia-south1`. Is it ENABLED? Did its last attempt succeed?
      2. The invocation: `gcloud run jobs executions list --job=${var.orchestrator_job_name}
         --region=asia-south1`. Nothing listed means the scheduler never reached Cloud Run —
         an IAM or OIDC problem, not an application one.
      3. Whether the image still starts. A revision that cannot start produces no execution.
      4. Then re-run by hand: `gcloud run jobs execute ${var.orchestrator_job_name}
         --region=asia-south1`. Note this only recovers TODAY; yesterday's slot is a different
         slot and needs `--now=<DATE>T12:00:00Z` to be picked up.

      Cloud Scheduler is the only scheduled thing in this project — nothing else has a cadence to
      lose, which is also why this policy names one job rather than being generic.
    EOT
  }

  conditions {
    display_name = "no completed execution"

    condition_absent {
      filter = join(" AND ", [
        "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
        "resource.type=\"cloud_run_job\"",
        "resource.label.job_name=\"${var.orchestrator_job_name}\"",
      ])

      duration = "${var.orchestrator_silence_seconds}s"

      aggregations {
        alignment_period   = "3600s"
        per_series_aligner = "ALIGN_DELTA"
      }
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]

  alert_strategy {
    notification_rate_limit {
      period = "86400s"
    }
  }
}

# --- 5. Messages are stuck on a main subscription ---------------------------
#
# ONE CONDITION COVERING TWO FAILURES. A dead consumer stops acking and the age climbs; a consumer
# nacking in a loop redelivers for ever and the age also climbs. Both are "messages are not being
# processed", which is the thing worth knowing, and neither needs a log-based metric.
resource "google_monitoring_alert_policy" "messages_stuck" {
  project      = var.project_id
  display_name = "Pub/Sub: messages are not being processed"
  combiner     = "OR"

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **The oldest unacknowledged message on a main subscription is over
      ${var.stuck_message_age_seconds / 60} minutes old. Either the consumer is not running, or it
      is nacking the same message repeatedly.**

      Both look identical from outside and the distinction is the first thing to establish:

      1. Is the consumer alive? `csv-ingest-worker` and `streaming-consumer` are Cloud Run
         SERVICES running a poll loop at `min_instances=1`. Confirm instance count is not 0 — a
         poller that scaled to zero has stopped pulling.
      2. If it IS alive, it is nacking. Look for `chunk failed (nacked;` in its logs. A
         DETERMINISTIC failure — a parse error, a contract violation — will nack for ever and the
         retry is pure waste; it ends in the DLQ after `max_delivery_attempts`
         (100 on dis-ingress-ready-sub, 20 on dis-csv-received-sub).
      3. Fix the cause. Do not raise the deadline or the attempt count: that delays the DLQ
         without changing the outcome.

      This alert going quiet does NOT mean the problem was fixed — a message that reaches its
      attempt limit is dead-lettered and disappears from this metric. The DLQ alert picks it up.
    EOT
  }

  conditions {
    display_name = "oldest unacked message age on a non-DLQ subscription"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"pubsub.googleapis.com/subscription/oldest_unacked_message_age\"",
        "resource.type=\"pubsub_subscription\"",
        # MAIN subscriptions only. A DLQ legitimately holds old messages by design — that is what
        # a DLQ is — so including them here would double-report #1 and never clear.
        "resource.label.subscription_id=monitoring.regex.full_match(\"dis-(csv-received|ingress-ready)-sub\")",
      ])

      comparison      = "COMPARISON_GT"
      threshold_value = var.stuck_message_age_seconds
      duration        = "300s"

      aggregations {
        alignment_period     = "300s"
        per_series_aligner   = "ALIGN_MAX"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["resource.label.subscription_id"]
      }

      evaluation_missing_data = "EVALUATION_MISSING_DATA_INACTIVE"
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]
}

# --- 6. A tenant's sale data has stopped arriving --------------------------
#
# THE ONE AN OFF-THE-SHELF SETUP WOULD MISS, and the one that is RED FROM CREATION.
resource "google_monitoring_alert_policy" "tenant_data_stale" {
  project      = var.project_id
  display_name = "Synapse: a tenant's sale data has gone stale"
  combiner     = "OR"

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **A tenant's newest sale is more than ${var.stale_after_days} days old. Every rate-based
      analysis is refusing for that tenant — CORRECTLY — and the runs still SUCCEED every day.**

      This is why the alert exists: `satisfied` means every capability resolved, not that anything
      was found. A stale tenant produces `outcome=satisfied, actions_proposed=0`, which is
      byte-identical to a healthy day on which nothing was at risk. No execution-status alert can
      ever see it.

      ## THIS ALERT IS RED FROM THE MOMENT IT IS CREATED. READ THIS BEFORE CHANGING IT.

      The Body Shop's latest sale is 2026-07-19 — 17 days old when this policy was written — so
      this fires on creation and STAYS RED until sales data arrives. That is not a
      misconfiguration; it is the condition being true. It is outstanding item 6.

      **A permanently-red alert becomes wallpaper, and the mitigation is NOT a wider threshold.**
      Widening it so it does not fire is tuning the alert to make the demo work. There are exactly
      two legitimate responses and you are being asked to pick one:

      1. **FIX INGESTION** — the real fix. There is no automated sales path: the only route is a
         hand-run CSV upload. Clover ships snapshot only and produces no sale events; the Square
         orders puller does not exist. And the last attempt FAILED — see the DLQ alert: a
         2026-07-30 CSV died on `source_sale_timestamp` date parsing and is sitting in
         `dis-ingress-ready-dlq`. Recovering that message is the shortest path to green.
      2. **DECIDE THE TENANT IS DORMANT** and disable its provisions
         (`synapse.provision.disabled_at`), which removes it from the sweep and from this metric
         honestly, rather than hiding it behind a threshold.

      `${var.stale_after_days}` days matches the strictest freshness threshold any analysis
      declares and `synapse.orchestrator.freshness.STALE_AFTER_DAYS`. Changing it here alone makes
      the alert and the log line disagree.

      A tenant with `ever_sold=false` has NEVER sent a sale — the age is time since provisioning,
      not since a sale. That is a different problem: nothing has ever worked for it.
    EOT
  }

  conditions {
    display_name = "newest sale older than the freshness threshold"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"logging.googleapis.com/user/${google_logging_metric.synapse_sale_age_days.name}\"",
        "resource.type=\"cloud_run_job\"",
      ])

      comparison      = "COMPARISON_GT"
      threshold_value = var.stale_after_days
      duration        = "0s"

      aggregations {
        # 26 hours: the emission is DAILY, so a shorter window has no points most of the time and
        # the condition would flap between "breach" and "no data" every hour.
        alignment_period     = "93600s"
        per_series_aligner   = "ALIGN_MAX"
        cross_series_reducer = "REDUCE_MAX"
        group_by_fields      = ["metric.label.tenant_id", "metric.label.ever_sold"]
      }

      # ACTIVE, AND THIS IS THE OPPOSITE OF #2 AND #3 ON PURPOSE.
      #
      # This metric is written by the orchestrator on every sweep for EVERY tenant, healthy ones
      # included. So NO DATA does not mean "nothing is stale" — it means the emitter stopped, and
      # an absence-detector that has itself gone absent is exactly the guard that silently never
      # fires. Treating missing data as a breach means the failure of the freshness signal fires
      # the freshness alert, rather than needing a seventh policy to watch the sixth.
      evaluation_missing_data = "EVALUATION_MISSING_DATA_ACTIVE"
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]

  # Known-red. Without this it re-notifies every evaluation for as long as ingestion is broken,
  # which is precisely how the team learns to filter these to a folder.
  alert_strategy {
    notification_rate_limit {
      period = "86400s"
    }
  }
}
