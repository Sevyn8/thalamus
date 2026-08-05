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
# TERRAFORM VALIDATES SCHEMA, NOT SEMANTICS
# =============================================================================
# `terraform validate` passed. `terraform plan` passed. THE API THEN REJECTED FIVE OF THE SIX
# POLICIES. Every field was the correct type in the correct block; the COMBINATIONS were ones the
# Monitoring API refuses. A schema check cannot see that, and neither can a plan — a plan asks
# "is this well-formed and what would change", never "will the service accept it".
#
# The three rejections, kept because each is a rule nothing in the provider states:
#
#   1. notification_rate_limit is legal ONLY on a log-MATCH policy (condition_matched_log). A
#      condition_threshold reading a logging.googleapis.com/user/ metric is NOT one — it is an
#      ordinary metric policy over a log-derived metric. Cost us three policies.
#   2. evaluation_missing_data cannot be paired with duration = "0s". A missing-data policy needs
#      a non-zero window in which to decide data is absent rather than late.
#   3. condition_absent duration maxes at 23h30m — SHORTER than the daily cadence it was written
#      to monitor, which makes it structurally unusable here rather than merely capped. See #4.
#
# THE ONLY CHECK FOR THIS CLASS IS AN APPLY. Nothing static reaches it, so an alerting module is
# not "done" when it validates; it is done when the API has accepted it.
#
# AND THE FIRST APPLY WAS PARTIAL, WHICH CHANGES WHAT A RE-APPLY IS. Four resources were created
# before the failures — the notification channel, both log-based metrics, and messages_stuck. The
# other five policies do not exist. So a re-apply is a RECONCILE, not a fresh start: expect
# creates for five policies and no-ops for the four that already exist. If a create fails again,
# the successful ones stay; this module is safe to re-apply repeatedly and that is deliberate,
# because getting the semantics right took more than one round trip.
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

  # LINEAR, WIDTH 1 DAY — and the exact boundaries are load-bearing for the alert.
  #
  # This was exponential (scale 1, growth 2 → boundaries 1,2,4,8,16,32,64…1024) and that
  # QUANTISES THE THRESHOLD PRECISELY WHERE IT MUST BE SHARP: the policy compares against 3 days,
  # and 3 sits inside the bucket [2,4). A percentile read back out of that bucket cannot tell 3.0
  # from 3.9, so the alert would fire or not on an interpolation artefact rather than on the data.
  # 17 days landed in [16,32) for the same reason.
  #
  # `sale_age_days` is an INTEGER NUMBER OF DAYS, so width-1 buckets are LOSSLESS for the values
  # that actually exist — there is no sub-day information to preserve. 60 finite buckets give
  # exact resolution from 0 to 60 days; beyond that everything lands in the overflow bucket, which
  # is correct because past two months "more stale" is not an actionable distinction.
  #
  # Cloud Logging's own reference is the source: bucket configuration determines precision, and
  # narrower buckets give finer granularity. Changing this is an in-place update (verified by
  # plan: "will be updated in-place", 0 to destroy) and it is FREE NOW because the metric holds no
  # data. It stops being free the moment it does.
  bucket_options {
    linear_buckets {
      num_finite_buckets = 60
      width              = 1
      offset             = 0
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

  # NO notification_rate_limit. The API refuses it on anything but a log-MATCH policy
  # (condition_matched_log): "only log-based alert policies may specify a notification rate
  # limit". A condition_threshold over a logging.googleapis.com/user/ metric is NOT that — it is
  # an ordinary metric-threshold policy that happens to read a log-derived metric. None of the six
  # here can use it. See the header on schema-vs-semantics.
  #
  # Nothing is lost for THIS policy: Monitoring notifies when an incident opens and when it
  # closes, not repeatedly while it stays open, so a DLQ message sitting for days produces one
  # notification rather than a stream.
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
      # 60s, NOT 0s. The API refuses duration="0s" together with evaluation_missing_data: a
      # missing-data policy needs a non-zero window to decide data is actually absent rather
      # than merely late. It does NOT change when this fires — ALIGN_DELTA over a 600s alignment
      # holds the aligned value for the whole period, so the breach is already persistent by the
      # time 60s has passed.
      duration = "60s"

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
      # 60s, NOT 0s. The API refuses duration="0s" together with evaluation_missing_data: a
      # missing-data policy needs a non-zero window to decide data is actually absent rather
      # than merely late. It does NOT change when this fires — ALIGN_DELTA over a 600s alignment
      # holds the aligned value for the whole period, so the breach is already persistent by the
      # time 60s has passed.
      duration = "60s"

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
# THE ABSENCE CASE, AND condition_absent CANNOT DO IT. This was written as condition_absent and
# the API rejected it: DURATION MAXES AT 23h30m (84600s). That is not a syntax problem, it is a
# design one — the cap is SHORTER THAN THE CADENCE BEING MONITORED. A 23h30m absence window on a
# daily job goes "absent" thirty minutes before every scheduled run, so it would fire once a day,
# for ever, on a perfectly healthy system. condition_absent cannot monitor a daily cadence at all.
#
# THE REPLACEMENT: condition_threshold, COMPARISON_LT 1, over a 24h ALIGN_DELTA window, with
# evaluation_missing_data ACTIVE.
#
# AND THE COMPARISON IS NOT WHAT FIRES IT. This is the non-obvious part and it was MEASURED rather
# than assumed. `completed_execution_count` is a sparse DELTA counter: it emits NOTHING on a day
# with no executions, it does not emit a zero. Verified against the live metric — 7 days of
# history aligned to 86400s returned ONE point (value 2, both of the orchestrator's runs in a
# single bucket), not seven points with five zeros.
#
# So `< 1` can never match on data, because there is no zero to be below. THE ENTIRE MECHANISM IS
# evaluation_missing_data = ACTIVE: no point in the window is a breach. The LT comparison exists
# to give the condition a well-formed shape and to catch the case where a zero IS somehow emitted;
# it is not the trigger.
#
# WHY THIS DOES NOT INHERIT condition_absent's FALSE POSITIVE. The alignment window SLIDES. At
# 21:29 UTC — one minute before the next scheduled run — the trailing 24 hours still contains
# yesterday's 21:30 execution, so there IS a point and the condition is satisfied. condition_absent
# failed precisely because its window could not reach back a full day; a 24h delta window can.
# `duration` then absorbs a late run: the missing state must persist an hour before it fires.
#
# ONE UNVERIFIED SEMANTIC, stated rather than discovered. The monitoring READ api accepts
# alignment periods well past 24h (86400s, 90000s and 172800s all returned data), but the ALERT
# POLICY validator is a different code path and its ceiling could not be tested without an apply —
# which is the header's whole point. 86400s is used because it is the documented maximum for
# alerting and is sufficient here. If the apply rejects it, the error will name alignmentPeriod and
# the fallback is 43200s (12h) with `duration` raised to cover the rest of the day.
resource "google_monitoring_alert_policy" "orchestrator_did_not_run" {
  project      = var.project_id
  display_name = "Synapse orchestrator: no execution in over 24 hours"
  combiner     = "OR"

  documentation {
    mime_type = "text/markdown"
    content   = <<-EOT
      **The orchestrator has not completed an execution in over 24 hours. It runs daily. Nothing
      analysed anything yesterday, and no failure was reported because nothing ran to fail.**

      This is the failure that has no error message. Everything is green because everything is
      absent. Note what this alert is actually detecting: the execution-count metric stopped
      producing points. It does not emit a zero when idle, so "no data" IS the signal.

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
    display_name = "fewer than one completed execution in the trailing 24h"

    condition_threshold {
      filter = join(" AND ", [
        "metric.type=\"run.googleapis.com/job/completed_execution_count\"",
        "resource.type=\"cloud_run_job\"",
        "resource.label.job_name=\"${var.orchestrator_job_name}\"",
      ])

      comparison      = "COMPARISON_LT"
      threshold_value = 1

      # An hour of tolerance for a late run, so a scheduler retry or a slow start does not page.
      # Well inside the 84600s ceiling that killed condition_absent.
      duration = "3600s"

      aggregations {
        # 24h, matching the cadence. A SLIDING window this wide always contains the previous run
        # until a full day has passed without one — which is the property condition_absent could
        # not have, since its duration was capped below the cadence.
        alignment_period   = "86400s"
        per_series_aligner = "ALIGN_DELTA"
      }

      # THIS IS THE ACTUAL TRIGGER, not the LT comparison above. The metric is sparse: no
      # executions means no points, verified against live data. A missing series is the failure.
      evaluation_missing_data = "EVALUATION_MISSING_DATA_ACTIVE"
    }
  }

  notification_channels = [google_monitoring_notification_channel.email.id]

  # NO notification_rate_limit — the API rejects it outside log-MATCH policies. See the header.
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
      # 60s, NOT 0s. The API refuses duration="0s" together with evaluation_missing_data: a
      # missing-data policy needs a non-zero window to decide data is actually absent rather
      # than merely late. It does NOT change when this fires — ALIGN_DELTA over a 600s alignment
      # holds the aligned value for the whole period, so the breach is already persistent by the
      # time 60s has passed.
      duration = "60s"

      aggregations {
        # 25 HOURS, WHICH IS THE MAXIMUM. The alert-policy alignment ceiling is 90000s; this
        # carried 93600s (26h) from the original design and the API rejected it. It was the only
        # one of the six above the ceiling — every other window here is 600s or less.
        #
        # THE INTERACTION THAT MAKES THE EXACT NUMBER MATTER, and it is between two settings that
        # look independent:
        #
        #   evaluation_missing_data = ACTIVE  +  an emission that happens ONCE PER DAY
        #
        # The freshness metric is written by the daily sweep. With a 24h window, a sweep ten
        # minutes late leaves a moment where the window holds ZERO points — and ACTIVE means no
        # data IS a breach. So a LATE SWEEP WOULD FIRE THE STALE-DATA ALERT: lateness would be
        # reported as staleness, on a tenant whose data is fine. That is a false positive of
        # precisely the kind that turns an alert into wallpaper, which is the thing this policy's
        # own documentation warns about.
        #
        # THE RULE: with ACTIVE and a periodic emission, the window must exceed the emission
        # cadence by enough to absorb a late producer, or lateness reads as absence. 25h gives an
        # hour of slack against a daily sweep and is as much as the API allows.
        #
        # orchestrator_did_not_run has the same ACTIVE + daily pairing and a 24h window, and is
        # safe by a DIFFERENT mechanism — its duration is 3600s, so a brief empty window has to
        # persist an hour before firing. Do not "make them consistent": each absorbs lateness in
        # one place, and this one absorbs it in the window because its duration is only 60s.
        alignment_period = "90000s"

        # ALIGN_PERCENTILE_99, AND IT IS THE ONLY VIABLE CHOICE — not a preference.
        #
        # This metric is DELTA + DISTRIBUTION, and that shape is FORCED: a Cloud Logging COUNTER
        # metric (DELTA/INT64) only counts entries and cannot extract a value from a field, so any
        # metric carrying a number out of a log line must be a distribution.
        #
        # The Aligner reference decides the rest. The rows, quoted:
        #   ALIGN_MAX   "valid for GAUGE and DELTA metrics with NUMERIC values"    -> illegal here
        #   ALIGN_MEAN  "…with NUMERIC values"                                     -> illegal here
        #   ALIGN_SUM   "…numeric AND DISTRIBUTION values … result is the same
        #                valueType as the input"                -> legal, but yields a DISTRIBUTION
        #   ALIGN_DELTA "valid for CUMULATIVE and DELTA … same valueType as input" -> same problem
        #   ALIGN_PERCENTILE_99 "valid for GAUGE and DELTA metrics with DISTRIBUTION values.
        #                The output is a GAUGE metric with valueType DOUBLE."      -> legal AND scalar
        #
        # A condition_threshold needs a NUMBER to compare against 3. The percentile aligners are
        # the only ones that are both legal for DELTA+DISTRIBUTION and produce one. ALIGN_MAX was
        # written here first and the API rejected it — see the deploy sequence in the header for
        # the read-only check that catches this class before an apply.
        per_series_aligner = "ALIGN_PERCENTILE_99"

        # A PERCENTILE IS NOT ADDITIVE, which is the property this alert depends on. A tenant that
        # emits twice in the window — a scheduler retry, an operator re-run — must not read as
        # double its age. p99 of {17, 17} is 17; a summing aligner would have been wrong for an
        # age even if its output could be thresholded.
        #
        # REDUCE_MAX is legal because it is applied to the ALIGNED output, which is DOUBLE:
        # "REDUCE_MAX: DELTA/GAUGE with numeric values". It would be illegal directly on the
        # distribution — which is exactly the error ALIGN_SUM produced.
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
  # NO notification_rate_limit (the API rejects it outside log-MATCH policies) — BUT THE INTENT
  # THIS PROTECTED IS REAL AND THIS POLICY IS THE ONE THAT NEEDS IT, so it is preserved by a
  # different mechanism.
  #
  # THE PROBLEM: this condition is TRUE FROM CREATION and stays true until sales data arrives.
  # Monitoring notifies on incident OPEN and CLOSE, not while an incident stays open — so one
  # long-lived incident is quiet. The risk is CHURN: if the incident keeps closing and re-opening,
  # each re-open notifies, and a daily close/re-open cycle is exactly how this becomes wallpaper.
  #
  # WHY IT WOULD CHURN HERE: the freshness metric is written ONCE PER DAY, so the series is sparse
  # by construction. With evaluation_missing_data ACTIVE, the gap between daily emissions can look
  # like a resolution followed by a fresh breach. auto_close is the timer Monitoring waits before
  # closing an incident whose data has stopped arriving — so setting it LONG (7 days, the maximum)
  # keeps one open incident across those gaps instead of minting a new one every day.
  alert_strategy {
    auto_close = "604800s"
  }
}
