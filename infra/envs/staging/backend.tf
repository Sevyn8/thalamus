# Remote state for the Thalamus staging waves (1-4), in the pre-existing
# org-shared bucket. The bootstrap layer (infra/bootstrap) stays LOCAL state and
# must NOT use this backend.
#
# Note: Terraform backend blocks cannot interpolate variables, so the bucket and
# prefix are literals here. They mirror var.state_prefix in variables.tf, which
# exists only as documentation of this value.
terraform {
  backend "gcs" {
    bucket = "sevyn8-thalamus-tfstate"
    prefix = "thalamus/staging"
  }
}
