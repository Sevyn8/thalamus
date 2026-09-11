###############################################################################
# axon-sender: Axon's poll loop over axon-send-requested.
#
# THE SHAPE IS streaming-consumer's AND NOT THE ORCHESTRATOR'S, and that is the
# one decision the rest of this file follows from. A scheduled job runs on a
# cadence and exits; a sender has no cadence, it has a queue, and a queue drained
# on a schedule is a queue with latency equal to the schedule. So: a Cloud Run
# SERVICE, min_instances = 1, cpu_idle = false, /healthz for the startup probe.
#
# WHAT THIS SERVICE CAN DO, WHICH IS DELIBERATELY ALMOST NOTHING:
#   1. Subscribe to ONE subscription. No publisher grant, no topic input.
#   2. INSERT into ONE table, as axon_sender, which holds no SELECT anywhere.
#   3. Talk to SendGrid over the public internet.
# It has no invoker binding, no read privilege on any database, and no route but
# the health probe.
#
# ITS OWN SERVICE ACCOUNT, not the default compute identity. That identity is a
# standing HIGH finding in this estate (two frontends share it and it holds
# secretAccessor on real credentials), and a new service is the cheapest possible
# moment not to inherit it.
###############################################################################

resource "google_service_account" "axon_sender" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "axon-sender runtime"
  description  = "Drains axon-send-requested and appends to axon.platform_deliveries. Subscriber on one subscription, accessor on two secrets, and nothing else."
}

# THE ONE SUBSCRIPTION. Resource-scoped rather than project-wide: a project-level
# roles/pubsub.subscriber would let this service drain every queue in the estate,
# including the dead-letter lanes whose whole purpose is that nothing drains them.
resource "google_pubsub_subscription_iam_member" "send_subscriber" {
  project      = var.project_id
  subscription = var.subscription_name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${google_service_account.axon_sender.email}"
}

# The startup check calls get_subscription before the loop begins, which needs
# viewer. Kept separate from the subscriber binding above so that removing the
# check does not silently leave a wider grant behind.
resource "google_project_iam_member" "pubsub_viewer" {
  project = var.project_id
  role    = "roles/pubsub.viewer"
  member  = "serviceAccount:${google_service_account.axon_sender.email}"
}

# --- Secrets. Data sources, so a missing secret fails the PLAN, not the boot. ---
#
# ALL FOUR PIECES OF EACH LAND HERE: the data source, the IAM member, the env
# block, and the depends_on entry. That sentence is written out rather than
# assumed because this once shipped the config change and the env var and NOT
# the wiring, and the write path sat dead in staging for two days behind a
# green apply. The depends_on half is checked rather than remembered, by
# tests/test_axon_sender_posture.py, which parses this file.

data "google_secret_manager_secret" "sender_url" {
  project   = var.project_id
  secret_id = var.secret_sender_url
}

resource "google_secret_manager_secret_iam_member" "sender_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.sender_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.axon_sender.email}"
}

data "google_secret_manager_secret" "sendgrid_api_key" {
  project   = var.project_id
  secret_id = var.secret_sendgrid_api_key
}

resource "google_secret_manager_secret_iam_member" "sendgrid_api_key" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.sendgrid_api_key.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.axon_sender.email}"
}

resource "google_cloud_run_v2_service" "axon_sender" {
  deletion_protection = false

  project  = var.project_id
  name     = var.service_name
  location = var.region

  # INGRESS_TRAFFIC_INTERNAL_ONLY. The service has no callers: the work is an
  # outbound pull and the only inbound request is Cloud Run's own health probe,
  # which is not subject to ingress rules. Nothing needs to reach this URL, so
  # nothing should be able to.
  #
  # AND NO INVOKER BINDING AT ALL, which is the half that actually matters. A
  # service with no run.invoker member cannot be called by anyone regardless of
  # ingress. This is the fourth service in this estate to ship without the
  # `allUsers` binding the standing HIGH finding is about.
  ingress = "INGRESS_TRAFFIC_INTERNAL_ONLY"

  template {
    service_account = google_service_account.axon_sender.email

    vpc_access {
      connector = var.vpc_connector_id
      # PRIVATE_RANGES_ONLY: Cloud SQL is private-IP and goes through the
      # connector; SendGrid is public and leaves over the default internet path.
      # Same posture, same reason, as the other services that reach a provider.
      egress = "PRIVATE_RANGES_ONLY"
    }

    scaling {
      # ONE, NOT ZERO, AND IT IS THE WHOLE REASON THIS IS A SERVICE. At zero the
      # loop scales away and the queue stops draining, and nothing wakes it:
      # there is no inbound request, so there is no cold-start trigger. The
      # backlog would grow silently until somebody noticed the alert on message
      # age, which is a slow way to discover a stopped consumer.
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      # The health server binds the Cloud-Run-injected $PORT.
      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
        # cpu_idle = false: CPU STAYS ALLOCATED so the background pull loop keeps
        # running when no HTTP request is in flight. At the default (true) the
        # loop is throttled to whatever the health probe happens to wake, and the
        # queue drains at a rate nobody chose and nothing reports.
        cpu_idle          = false
        startup_cpu_boost = true
      }

      env {
        name  = "GOOGLE_CLOUD_PROJECT"
        value = var.project_id
      }

      env {
        name  = "RUN_HEALTH_SERVER"
        value = "true"
      }

      env {
        name  = "DIS_EXPECTED_DATABASE"
        value = var.expected_database
      }

      env {
        name  = "AXON_SENDGRID_FROM_EMAIL"
        value = var.sendgrid_from_email
      }

      # THE WRITE CREDENTIAL, and the only one this service has. axon_sender:
      # INSERT on axon.platform_deliveries, no SELECT anywhere, nothing on the
      # tenant ledger. It moved HERE from synapse-ui-server because that
      # service stopped writing the ledger when the enable route became a
      # publish. A credential mounted on a process that no longer uses it is a
      # privilege nobody is accounting for.
      env {
        name = "AXON_SENDER_URL"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.sender_url.secret_id
            version = "latest"
          }
        }
      }

      env {
        name = "AXON_SENDGRID_API_KEY"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.sendgrid_api_key.secret_id
            version = "latest"
          }
        }
      }

      # /healthz reports on the LOOP, not on the web server: the handler reads a
      # heartbeat the loop writes once per pass and answers 503 when it goes
      # stale. A probe that returned 200 because uvicorn is up would report a
      # hung loop as healthy for the life of the container.
      startup_probe {
        http_get {
          path = "/healthz"
          port = 8080
        }
        initial_delay_seconds = 10
        period_seconds        = 5
        failure_threshold     = 12
        timeout_seconds       = 3
      }
    }

    timeout = "60s"
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  # EVERY iam_member IN THIS MODULE MUST BE LISTED. The implicit dependency from
  # a secret env block is on the DATA SOURCE, not on the grant, so Terraform is
  # free to create the revision before the binding exists or propagates and the
  # container then fails to read its own credential. That has happened before,
  # and tests/test_axon_sender_posture.py parses this file to check the list
  # rather than leaving it to a reader to remember.
  depends_on = [
    google_secret_manager_secret_iam_member.sender_url,
    google_secret_manager_secret_iam_member.sendgrid_api_key,
    google_pubsub_subscription_iam_member.send_subscriber,
    google_project_iam_member.pubsub_viewer,
  ]

  # NO allUsers ON run.invoker, EVER, ON THIS SERVICE. There is no binding block
  # here at all, which is the strongest form: a service with no invoker member
  # is unreachable by anyone. The posture test asserts the absence rather than
  # trusting this comment.
  lifecycle {
    precondition {
      condition     = var.min_instances >= 1
      error_message = "axon-sender must run at least one instance. At zero the pull loop scales away and the queue stops draining, with nothing to wake it: the work is an outbound pull, so there is no inbound request to trigger a cold start."
    }

    # THE SERVICE-LEVEL scaling BLOCK IS IGNORED. THE TEMPLATE ONE IS NOT, AND THE
    # PRECONDITION ABOVE STILL GOVERNS IT.
    #
    # google_cloud_run_v2_service has TWO scaling blocks, and they are SIBLINGS in the
    # address space rather than one nested inside the other:
    #
    #   scaling            manual_instance_count, min_instance_count, scaling_mode
    #   template.scaling   min_instance_count, max_instance_count
    #
    # `ignore_changes = [scaling]` names the first. The second is reached through the
    # `template` attribute, which is not in this list, so the block inside `template`
    # stays fully managed and var.min_instances keeps setting the poll loop's floor.
    #
    # THAT IS CHECKABLE RATHER THAN ASSERTED. manual_instance_count exists ONLY on the
    # top-level block, and the perpetual diff this removes was on manual_instance_count
    # and min_instance_count together, so the diff cannot have been template.scaling.
    #
    # WHY IGNORE RATHER THAN DECLARE. This module never declared a service-level scaling
    # block, and the Cloud Run v2 API re-materializes one on every read with zeros that
    # mean "absent". Terraform reads the zeros, finds nothing configured, and proposes
    # removing what it cannot remove, on every plan. That trains people to skim plans,
    # which is the actual cost. Declaring a block to match the zeros would be writing
    # configuration to satisfy a read rather than to state an intent, and it would put a
    # second min_instance_count in this resource, one line from the one that must never
    # be zero. cloud-run-service-synapse-ui-server carries the same ignore for the same
    # diff and keeps its template scaling managed alongside it.
    #
    # THE COST: a service-level scaling change made outside Terraform is neither reverted
    # nor reported here. Nothing in this estate sets one and scaling_mode is unused, so
    # there is nothing today for that blindness to hide.
    ignore_changes = [scaling]
  }
}
