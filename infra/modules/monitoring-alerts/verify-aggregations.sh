#!/usr/bin/env bash
#
# PRE-APPLY CHECK. Run this BEFORE `terraform apply`, every time this module changes.
#
# =============================================================================
# WHY THIS EXISTS
# =============================================================================
# Slice 9 cost EIGHT API rejections, one plan-apply cycle each, and every one of them was
# knowable beforehand. `terraform validate` and `terraform plan` check schema — is the field the
# right type, in the right block — and the Monitoring API rejects COMBINATIONS: an aligner that
# cannot apply to a metric's valueType, a reducer that cannot apply to the aligner's OUTPUT type,
# an alignment period past a ceiling. No static check reaches any of that.
#
# But `timeSeries.list` DOES. It validates the same aggregation triple the alert policy will be
# evaluated with, it is READ-ONLY, and it costs nothing. Running it against each policy's exact
# filter + aligner + reducer + alignment period turns a class of failure that used to need an
# apply into a check that needs a token.
#
# This is the same discipline as verifying a container image from the inside rather than trusting
# the build log: exercise the thing the platform will actually evaluate, before committing to it.
#
# WHAT IT DOES NOT COVER, stated so the pass is not read as more than it is:
#   - notification_rate_limit legality (a policy-level rule, not an aggregation one)
#   - duration / evaluation_missing_data pairing
#   - condition_absent's 23h30m duration cap
#   - whether the notification channel is VERIFIED (see the deploy sequence below)
# Those three bit us too and none is visible here. A clean run means the aggregations are legal,
# not that the apply will succeed.
#
# =============================================================================
# DEPLOY SEQUENCE
# =============================================================================
#   1. ./verify-aggregations.sh sevyn8-thalamus-staging     <- this script, must be all-ACCEPTED
#   2. terraform plan
#   3. terraform apply
#   4. Confirm all six policies exist:
#        gcloud alpha monitoring policies list --project=<P>   (or the REST alertPolicies endpoint)
#   5. CLICK THE VERIFICATION EMAIL. An email notification channel delivers NOTHING until its
#      confirmation link is followed. Check with:
#        curl -s -H "Authorization: Bearer $(gcloud auth print-access-token)" \
#          "https://monitoring.googleapis.com/v3/projects/<P>/notificationChannels" \
#          | python3 -c 'import sys,json;[print(c["labels"]["email_address"], c.get("verificationStatus")) for c in json.load(sys.stdin)["notificationChannels"]]'
#      An unverified channel makes all six policies inert while looking configured.
#
# Usage:  ./verify-aggregations.sh [PROJECT_ID]

set -uo pipefail

PROJECT="${1:-sevyn8-thalamus-staging}"
TOKEN="$(gcloud auth print-access-token 2>/dev/null)" || { echo "no access token"; exit 1; }
END="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
START="$(date -u -d '2 hours ago' +%Y-%m-%dT%H:%M:%SZ)"

# THE SIX, mirroring modules/monitoring-alerts/main.tf. If a policy's aggregation changes there
# and not here, this script validates a combination the module does not use — a check that passes
# while covering the wrong thing. tests/unit/test_alert_aggregations.py compares the two and fails
# on drift, which is why these values may be restated here at all.
#
#   name | metric.type | aligner | reducer (empty = none) | alignment period
POLICIES=(
  "dlq_not_empty|pubsub.googleapis.com/subscription/num_undelivered_messages|ALIGN_MAX|REDUCE_MAX|300s"
  "orchestrator_execution_failed|run.googleapis.com/job/completed_execution_count|ALIGN_DELTA||600s"
  "synapse_slot_failed|logging.googleapis.com/user/synapse/slot_failed|ALIGN_DELTA|REDUCE_SUM|600s"
  "orchestrator_did_not_run|run.googleapis.com/job/completed_execution_count|ALIGN_DELTA||86400s"
  "messages_stuck|pubsub.googleapis.com/subscription/oldest_unacked_message_age|ALIGN_MAX|REDUCE_MAX|300s"
  "tenant_data_stale|logging.googleapis.com/user/synapse/tenant_sale_age_days|ALIGN_PERCENTILE_99|REDUCE_MAX|90000s"
)

fail=0
printf '%-32s %-22s %-12s %-8s %s\n' POLICY ALIGNER REDUCER ALIGN RESULT
for row in "${POLICIES[@]}"; do
  IFS='|' read -r name metric aligner reducer align <<<"$row"

  args=(
    --data-urlencode "filter=metric.type=\"${metric}\""
    --data-urlencode "interval.startTime=${START}"
    --data-urlencode "interval.endTime=${END}"
    --data-urlencode "aggregation.alignmentPeriod=${align}"
    --data-urlencode "aggregation.perSeriesAligner=${aligner}"
  )
  [[ -n "$reducer" ]] && args+=(
    --data-urlencode "aggregation.crossSeriesReducer=${reducer}"
    --data-urlencode "aggregation.groupByFields=resource.label.project_id"
  )

  body="$(curl -s -G -H "Authorization: Bearer ${TOKEN}" \
    "https://monitoring.googleapis.com/v3/projects/${PROJECT}/timeSeries" "${args[@]}")"

  if grep -q '"error"' <<<"$body"; then
    msg="$(python3 -c 'import sys,json;print(json.load(sys.stdin)["error"]["message"][:90])' <<<"$body")"
    printf '%-32s %-22s %-12s %-8s REJECTED %s\n' "$name" "$aligner" "${reducer:--}" "$align" "$msg"
    fail=1
  else
    # NOTE: an empty result set is a PASS. The aggregation was accepted; whether the metric has
    # data yet is a different question and several of these are legitimately empty until
    # something fails for the first time.
    printf '%-32s %-22s %-12s %-8s ACCEPTED\n' "$name" "$aligner" "${reducer:--}" "$align"
  fi
done

echo
if [[ $fail -eq 0 ]]; then
  echo "All six aggregations accepted. This does NOT cover rate limits, duration/missing-data"
  echo "pairing, or channel verification — see the header."
else
  echo "At least one aggregation would be rejected by the API. Read the Aligner/Reducer constraint"
  echo "table before changing a value: the fix is a row in that table, not the next combination."
fi
exit $fail
