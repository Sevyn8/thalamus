###############################################################################
# network: ONE VPC for the consolidated Thalamus data + service plane.
#
# Adapted from DIS's network module (~/projects/ithina-retail-dis/terraform/
# modules/network) in its create_vpc=true shape only. The create_vpc=false
# shared-attach branch is intentionally dropped: Thalamus staging is a fresh
# project with a fresh VPC, so there is nothing to attach to. CM's GKE secondary
# ranges are also dropped (no GKE this wave; staging is all Cloud Run).
#
# Provisions: VPC + subnet (private Google access) + PSA /16 range + Service
# Networking connection (for Cloud SQL private IP) + Serverless VPC Access
# connector (Cloud Run -> private Cloud SQL) + Cloud Router + Cloud NAT.
###############################################################################

resource "google_compute_network" "vpc" {
  project                 = var.project_id
  name                    = "${var.name_prefix}-vpc"
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "Thalamus ${var.name_prefix} shared VPC (staging)."
}

resource "google_compute_subnetwork" "subnet" {
  project                  = var.project_id
  name                     = "${var.name_prefix}-subnet"
  region                   = var.region
  network                  = google_compute_network.vpc.id
  ip_cidr_range            = var.subnet_cidr
  private_ip_google_access = true
}

# Reserved range Google-managed services (Cloud SQL private IP) peer into.
resource "google_compute_global_address" "psa_range" {
  project       = var.project_id
  name          = "${var.name_prefix}-psa-range"
  purpose       = "VPC_PEERING"
  address_type  = "INTERNAL"
  prefix_length = 16
  network       = google_compute_network.vpc.id
  description   = "Reserved range for Google-managed services (Cloud SQL private IP)."
}

# Service Networking peering. Required before Cloud SQL private IP can be created.
# deletion_policy ABANDON (carried from CM's network module) so a later teardown
# does not wedge on the peering connection.
resource "google_service_networking_connection" "psa" {
  network                 = google_compute_network.vpc.id
  service                 = "servicenetworking.googleapis.com"
  reserved_peering_ranges = [google_compute_global_address.psa_range.name]
  deletion_policy         = "ABANDON"
}

# Serverless VPC Access connector: Cloud Run services reach private Cloud SQL
# through this. This is the piece CM's network module lacked and DIS's had.
resource "google_vpc_access_connector" "connector" {
  project       = var.project_id
  name          = "${var.name_prefix}-vpcconn"
  region        = var.region
  network       = google_compute_network.vpc.name
  ip_cidr_range = var.connector_cidr
  min_instances = 2
  max_instances = 3
}

resource "google_compute_router" "router" {
  project = var.project_id
  name    = "${var.name_prefix}-router"
  region  = var.region
  network = google_compute_network.vpc.id
}

resource "google_compute_router_nat" "nat" {
  project                            = var.project_id
  name                               = "${var.name_prefix}-nat"
  router                             = google_compute_router.router.name
  region                             = var.region
  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "ALL_SUBNETWORKS_ALL_IP_RANGES"

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}
