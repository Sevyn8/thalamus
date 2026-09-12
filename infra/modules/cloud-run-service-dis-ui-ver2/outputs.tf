output "service_url" {
  value       = google_cloud_run_v2_service.dis_ui_ver2.uri
  description = "Public HTTPS URL of the DIS UI. Publicly callable at the IAM layer (allUsers invoker); the SPA's Auth0 session gates access to data."
}

output "service_name" {
  value = google_cloud_run_v2_service.dis_ui_ver2.name
}

output "service_account_email" {
  # READ FROM THE SERVICE, NOT FROM THE ACCOUNT. google_service_account.email is
  # what this module INTENDS to attach; template[0].service_account is what the
  # revision actually runs as. They agree, and this output is the thing that
  # would notice if they ever stopped agreeing.
  value       = google_cloud_run_v2_service.dis_ui_ver2.template[0].service_account
  description = "Runtime identity actually in use: the service's own dedicated SA (P1-IAM-001A), no longer the shared default compute identity. It holds no IAM bindings and is not a caller anywhere, so nothing should be granting it access."
}
