###############################################################################
# artifact-registry: one Docker repository for Thalamus service images
# (cm-backend now; DIS services in Wave 3, all under the same repo).
#
# CLEANUP POLICIES. Untagged digests accumulate one per build and nothing ever
# removed them: ~24 orphaned cm-backend digests against 13 tagged, ~10 orphaned
# dis-ui-ver2 against 14 tagged, more elsewhere. One-off deletions do not fix a
# per-build leak, so this is a policy.
#
# THIS REPOSITORY HOLDS EVERY IMAGE TERRAFORM PINS. A policy that deleted a
# tagged digest would fail a plan or an apply, and in the worst case leave a
# Cloud Run revision unable to pull. The entire safety argument is the
# keep-wins precedence rule, quoted verbatim from
# https://cloud.google.com/artifact-registry/docs/repositories/cleanup-policy so
# a future reader has the citation and not an assurance:
#
#   "When an artifact matches the criteria for both a delete policy and a keep
#    policy, the artifact is kept."
#
# That is why keep-all-tagged carries NO time bound. A rollback to an old tag is
# exactly the moment you cannot afford the image to be gone, so "tagged" is the
# whole condition - not "tagged and recent".
#
# Second protection, from the same page, which covers untagged CHILDREN of a
# tagged multi-arch index (a local buildx can produce these):
#
#   "Cleanup policies for Docker images don't delete images referenced by a
#    parent manifest. If the parent manifest is deleted, then any related images
#    are deleted when the cleanup policy is next run."
#
# REPOSITORY-WIDE ON PURPOSE: no package_name_prefixes on either policy, so a
# service added later inherits the protection instead of needing a policy edit.
# Every package here has the same tagged-vN shape.
#
# 90 DAYS, NOT 30, and please do not "optimise" this to 7d. There is no cost
# pressure - orphaned digests are pennies, builds are manual, and accumulation is
# a handful per build. The policy's job is to BOUND growth, not to minimise
# storage, and this is the first delete policy ever aimed at a repository every
# terraform pin depends on. The wide margin is the point.
#
# Conditions AND together ("If multiple entries are set, all must be satisfied"),
# so the delete rule requires untagged AND older than 90 days. Evaluation is a
# periodic background job that takes effect within roughly a day, so nothing is
# ever deleted moments after a push.
###############################################################################

resource "google_artifact_registry_repository" "this" {
  project       = var.project_id
  location      = var.region
  repository_id = var.repository_id
  format        = "DOCKER"
  description   = "Thalamus service container images (staging)."

  # Repository-wide kill switch for the policies below. Ships TRUE: the config
  # lands and the plan goes clean while deletions stay off, which separates "the
  # policy is attached" from "deletions have begun". Flipped to false only after
  # the would-delete set has been enumerated and read.
  #
  # WATCH THE FALSE. Once the flip lands this is false again - the SAME VALUE it
  # held before any of this, meaning the OPPOSITE thing. Before: false because no
  # policies existed, so there was nothing to suppress. After: false because the
  # policies are LIVE and deletions are enabled. Anyone comparing repository state
  # from before this work to after sees an unchanged boolean and could conclude
  # nothing happened; the two cleanup_policies blocks are what actually differ.
  cleanup_policy_dry_run = var.cleanup_policy_dry_run

  # The guarantee. Unconditional: every tagged version, every age, forever.
  cleanup_policies {
    id     = "keep-all-tagged"
    action = "KEEP"

    condition {
      tag_state = "TAGGED"
    }
  }

  # The collector. Untagged AND older than the grace period; anything younger
  # matches no policy at all and is therefore kept.
  cleanup_policies {
    id     = "delete-untagged-older-than-grace"
    action = "DELETE"

    condition {
      tag_state  = "UNTAGGED"
      older_than = var.untagged_grace_period
    }
  }
}
