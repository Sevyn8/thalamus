output "network_id" {
  value       = google_compute_network.vpc.id
  description = "Self link/id of the VPC."
}

output "network_self_link" {
  value = google_compute_network.vpc.self_link
}

output "subnet_id" {
  value = google_compute_subnetwork.subnet.id
}

output "vpc_connector_id" {
  value       = google_vpc_access_connector.connector.id
  description = "Serverless VPC Access connector id, for Cloud Run services (Waves 2-4)."
}

output "private_service_connection" {
  value       = google_service_networking_connection.psa.id
  description = "Service Networking connection id; cloud-sql depends_on this for ordering."
}
