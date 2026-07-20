variable "project_id" {
  type        = string
  description = "GCP project id (sevyn8-thalamus-staging)."
}

variable "region" {
  type        = string
  description = "Region for the subnet, connector, router, and NAT."
}

variable "name_prefix" {
  type        = string
  description = "Prefix for network resource names."
  default     = "thalamus"
}

variable "subnet_cidr" {
  type        = string
  description = "Primary subnet CIDR."
  default     = "10.20.0.0/24"
}

variable "connector_cidr" {
  type        = string
  description = "The /28 the Serverless VPC Access connector uses. Must not overlap subnet_cidr."
  default     = "10.8.0.0/28"
}
