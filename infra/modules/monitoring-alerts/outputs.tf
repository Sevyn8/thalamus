output "notification_channel_id" {
  value       = google_monitoring_notification_channel.email.id
  description = "The single email channel every policy notifies. Exposed so a later module can reuse it rather than creating a second one — two channels is how one of them stops being read."
}

output "policy_names" {
  value = [
    google_monitoring_alert_policy.dlq_not_empty.display_name,
    google_monitoring_alert_policy.orchestrator_execution_failed.display_name,
    google_monitoring_alert_policy.synapse_slot_failed.display_name,
    google_monitoring_alert_policy.orchestrator_did_not_run.display_name,
    google_monitoring_alert_policy.messages_stuck.display_name,
    google_monitoring_alert_policy.tenant_data_stale.display_name,
  ]
  description = "The six. Listed so `terraform output` answers \"what is watched\" without opening the console — the question that had no answer before this module."
}

output "log_metric_names" {
  value = [
    google_logging_metric.synapse_slot_failed.name,
    google_logging_metric.synapse_sale_age_days.name,
  ]
  description = "The two log-based metrics. Both depend on dis_core.logging flattening `extra` to the top level of jsonPayload."
}
