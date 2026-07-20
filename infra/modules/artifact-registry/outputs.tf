output "repository_id" {
  value = google_artifact_registry_repository.this.repository_id
}

output "repo_url" {
  description = "Base URL for image pushes: <region>-docker.pkg.dev/<project>/<repository_id>."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.this.repository_id}"
}
