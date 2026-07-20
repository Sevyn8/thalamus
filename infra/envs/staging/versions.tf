# Version pins match DIS and CM (both use terraform >= 1.6.0, google ~> 6.0,
# google-beta ~> 6.0, random ~> 3.6). Kept identical so the DIS/CM modules fold
# into modules/ in later waves without a provider-version bump.
terraform {
  required_version = ">= 1.6.0"

  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
