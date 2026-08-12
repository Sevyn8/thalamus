###############################################################################
# synapse-ui-server: the read-only BFF behind Synapse's superadmin console.
#
# Called SERVER-SIDE by cm-frontend's Next.js server components. The browser
# never reaches it, so it needs no public invoker binding and no CORS.
#
# READS AS synapse_reader, AND WRITES EXACTLY TWO TABLES AS TWO OTHER ROLES.
#
# This paragraph said "the synapse_reader DSN and nothing else" until slice 5d
# falsified it, and then named ONE write credential until 5e falsified that. The
# posture is now three DSNs and the shape is what matters: each write credential
# is ONE VERB ON ONE TABLE.
#
#   synapse_reader      every GET.
#   synapse_lifecycle   INSERT on synapse.action_events. The console records a
#                       snooze, dismissal or acknowledgement (slice 5d).
#   synapse_provisioner INSERT on synapse.provision, plus the two SELECTs its
#                       pre-flight cannot run without. The console enables a
#                       monitor for a tenant (slice 5e). NO UPDATE, so it cannot
#                       disable one or edit a timezone: enablement is one
#                       direction at the database, not by convention.
#
# NONE OF THEM IS synapse_writer, which is the ORCHESTRATOR's identity and holds
# INSERT on synapse.actions. No writer secret is granted, no writer env var is
# set, and the service refuses to START if SYNAPSE_WRITER_URL is present. That
# refusal is what made "8b must add a writer deliberately" happen twice as a
# visible act rather than as the discovery that one was already wired.
#
# AND THERE IS A NON-DATABASE ENV VAR NOW. CM_API_BASE_URL: provisioning is gated
# on a Customer Master permission, checked server-side against CM's /me/can-do
# with the caller's own Auth0 token. Synapse defines no permission of its own.
#
# ==========================================================================
# THE INVOKER BINDING: WHAT IT ACHIEVES, AND WHAT IT DOES NOT
# ==========================================================================
# Three facts, and the third is the one that would otherwise be misread:
#
#   1. THIS BINDING REMOVES ANONYMOUS ACCESS. That is the substance of the
#      standing HIGH ledger finding — every other HTTP service in this project
#      (cm-backend, cm-frontend, dis-ui-server, dis-ui-ver2) carries an
#      `allUsers` invoker binding with the JWT as the sole gate. This service
#      does not. It is the first one, which makes fixing the others a precedent
#      rather than a proposal.
#
#   2. IT DOES NOT RESTRICT THE CALLER TO cm-frontend. cm-frontend has NO
#      DEDICATED SERVICE ACCOUNT — it runs as the project's DEFAULT COMPUTE
#      identity, recorded as a ledger item in
#      infra/modules/cloud-run-service-cm-frontend/main.tf. dis-ui-ver2 runs as
#      the same identity.
#
#   3. SO ANY WORKLOAD RUNNING AS DEFAULT COMPUTE IN THIS PROJECT CAN INVOKE
#      THIS SERVICE, and "restricted to cm-frontend" would be a FALSE STATEMENT.
#      It is not written anywhere in this module for that reason.
#
# The real fix is giving cm-frontend a dedicated service account, which closes
# the ledger item and makes the member below mean what it appears to mean. That
# is ITS OWN SLICE WITH A WINDOW, not a side effect of a UI build: the two
# cm-frontend-* Auth0 secretAccessor grants were made OUT OF BAND, so a new
# service account must have them re-granted before the frontend can boot. Doing
# it silently here would risk an outage on a running frontend to improve a
# comment.
#
# NOT granted here, by design:
#   - No secretAccessor on the WRITER DSN. The write path this service has is
#     synapse_lifecycle, INSERT on synapse.action_events alone.
#   - No roles/cloudsql.client: Cloud SQL is reached over the private IP through
#     the VPC connector, at the TCP layer, as the orchestrator does.
#   - No Artifact Registry reader: image pulls use the Cloud Run service agent.
###############################################################################

# A DEDICATED runtime identity, unlike cm-frontend's. Every Terraform-managed
# service in this tree has one; the frontend's absence of one is the exception
# and the thing point 2 above is about.
resource "google_service_account" "synapse_ui_server" {
  project      = var.project_id
  account_id   = var.service_account_id
  display_name = "Synapse UI server (read-only BFF) runtime SA"
}

# The reader DSN, created out of band. The data source fails the PLAN if it is
# missing, which is the right time to find out.
data "google_secret_manager_secret" "reader_url" {
  project   = var.project_id
  secret_id = var.secret_reader_url
}

resource "google_secret_manager_secret_iam_member" "reader_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.reader_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.synapse_ui_server.email}"
}

# The lifecycle DSN, created out of band like the reader. UNLIKE the reader, its
# IAM policy was EMPTY: the secret existed and nothing could read it, so v6 and v7
# would have failed on the grant even had the env var been wired.
data "google_secret_manager_secret" "lifecycle_url" {
  project   = var.project_id
  secret_id = var.secret_lifecycle_url
}

resource "google_secret_manager_secret_iam_member" "lifecycle_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.lifecycle_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.synapse_ui_server.email}"
}

# The provisioner DSN (slice 5e). Created out of band like the other two.
#
# ALL FOUR PIECES LAND IN THIS SLICE, DELIBERATELY: this data source, the IAM
# member below it, the env block in the container, and the depends_on entry.
# Slice 5d shipped the config change and the env var without the wiring, and the
# write path sat dead in staging for two days behind a passing apply, because
# terraform validated a module that was internally consistent and simply did not
# set a variable the image required. The apply was green; the revision failed its
# health check; staging kept serving the previous one. Nothing in a plan says
# "the container needs an env var you did not write".
data "google_secret_manager_secret" "provisioner_url" {
  project   = var.project_id
  secret_id = var.secret_provisioner_url
}

resource "google_secret_manager_secret_iam_member" "provisioner_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.provisioner_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.synapse_ui_server.email}"
}

# =============================================================================
# AXON: THREE SECRETS, AND ALL FOUR PIECES OF EACH LAND IN THE SLICE THAT ADDS IT.
# =============================================================================
# The data source, the IAM member, the env block and the depends_on entry. Slice
# 5d is the reason that sentence is written out rather than assumed: it shipped
# the config change and the env var and NOT the wiring, and the write path sat
# dead in staging for two days behind a green apply. A module that never
# references a variable cannot fail on it, and a plan cannot say "the container
# needs an env var you did not write".
#
# The depends_on half is checked rather than remembered:
# tests/test_deployment_posture.py::test_every_secret_iam_member_is_listed_in_the_services_depends_on
# PARSES this file, so both grants below are covered the moment they land.

# THE PUBLISHER GRANT, WHICH REPLACED THE SENDER'S DSN IN SLICE 2.
#
# This service used to hold axon_sender (INSERT on axon.platform_deliveries),
# because the 5e enable route sent in-process and wrote the ledger row itself. It
# now PUBLISHES one message to axon-send-requested and writes nothing; axon-sender
# does the send behind the queue. So the DSN moved there and this is what is left.
#
# THE REDUCTION IS THE POINT, not a side effect. A console that can no longer
# write the delivery ledger cannot corrupt it, and a credential mounted on a
# process that no longer uses it is a privilege nobody is accounting for.
#
# TOPIC-SCOPED, NOT PROJECT-WIDE. A project-level roles/pubsub.publisher would let
# this service publish to every topic in the estate, including DIS's ingress lanes
# and every dead-letter topic.
resource "google_pubsub_topic_iam_member" "axon_send_publisher" {
  project = var.project_id
  topic   = var.axon_send_topic
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${google_service_account.synapse_ui_server.email}"
}

# THE READ HALF OF THE PAIR (Axon slice 3). axon_reader holds SELECT on BOTH
# ledgers and no write verb anywhere, which is the exact opposite of the role
# above and is why it is a second secret rather than a second use of the first.
# Reusing the sender's DSN would have meant granting SELECT to the send path, so
# that the process which writes a ledger of who was contacted about what could
# also read it back.
#
# Created out of band like every other DSN here; grants come from
# infra/db-setup/sql/07_axon_reader_grant.sql.
data "google_secret_manager_secret" "axon_reader_url" {
  project   = var.project_id
  secret_id = var.secret_axon_reader_url
}

resource "google_secret_manager_secret_iam_member" "axon_reader_url" {
  project   = var.project_id
  secret_id = data.google_secret_manager_secret.axon_reader_url.secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.synapse_ui_server.email}"
}

# THE SENDGRID KEY IS GONE FROM THIS SERVICE, and its absence is deliberate. This
# process no longer talks to a provider: it publishes a message and returns. The
# key and the from-address moved to axon-sender's module, which is the only thing
# that now calls SendGrid. Same reason as the DSN above.

resource "google_cloud_run_v2_service" "synapse_ui_server" {
  deletion_protection = false

  project  = var.project_id
  name     = var.service_name
  location = var.region
  # ============================================================================
  # INGRESS IS OPEN, AND IAM IS THE CONTROL. THIS WAS INTERNAL_ONLY AND IT NEVER
  # WORKED — NOT ONCE, FOR ANY REQUEST.
  # ============================================================================
  # INTERNAL_ONLY admits traffic that arrives THROUGH A VPC. A *.run.app URL
  # resolves to a public IP, and cm-frontend has no VPC connector and no direct
  # VPC egress — see modules/cloud-run-service-cm-frontend, which documents the
  # absence deliberately ("never talks to Cloud SQL, so it needs no private
  # egress"). So every request from the console left over the public internet and
  # was refused AT THE EDGE. The container never ran. See the signature note below.
  #
  # THE MODULE ASSERTED A REQUIREMENT ON ITS CALLER AND THE CALLER WAS NEVER
  # INSPECTED. terraform validated, planned and applied it happily, because an
  # ingress rule is a claim about TWO services and terraform only ever sees one.
  #
  # WHAT SATISFYING IT WOULD HAVE COST, measured rather than guessed. cm-frontend
  # would need egress = ALL_TRAFFIC (PRIVATE_RANGES_ONLY does not route a public
  # run.app IP). Its server-side outbound surface is exactly three things:
  #
  #   Auth0    middleware.ts, on EVERY matched request — token exchange, JWKS,
  #            getSession. Public internet.
  #   this BFF the one call we are trying to enable.
  #   metadata 169.254.169.254, link-local, never routed via VPC egress at all.
  #
  # cm-backend is NOT on that list: every apiFetch caller in cm-frontend is a
  # client component, so the browser calls it directly and VPC egress cannot
  # touch it. Checked, because it was the assumed blast radius and it is not one.
  #
  # So the true cost is that AUTH0 — the login path of every request — moves
  # behind thalamus-vpcconn, min_instances = 2, max_instances = 3, default
  # machine type. Cloud NAT and Private Google Access already exist, so this is
  # cheap to BUILD and the expense is entirely at runtime: a fixed-capacity hop
  # and a new failure mode in front of authentication for every user, in order to
  # protect a READ-ONLY console that already requires a Google ID token AND a
  # PLATFORM claim. That trade is not worth making.
  #
  # WHAT WAS GIVEN UP, stated plainly rather than minimised. Ingress was the one
  # control that FAILS CLOSED if somebody adds an allUsers invoker binding — and
  # in this estate that is not hypothetical, it is the standing HIGH finding and
  # it has happened on four other HTTP services. IAM alone does not survive that
  # mistake. So the precondition on the invoker binding below is not decoration:
  # it is the replacement, aimed at the specific failure mode ingress was
  # covering, and it is cheaper and visible in a diff.
  #
  # TWO LAYERS REMAIN, AND THEY PROVE DIFFERENT THINGS: IAM proves the WORKLOAD
  # (a Google ID token for the caller SA, checked before the container is
  # reached), Auth0 proves the PERSON (a PLATFORM user_type claim, checked in
  # auth.py). This is still not the standing HIGH finding: there is no allUsers
  # binding here, and the precondition is what keeps it that way.
  #
  # IF INTERNAL_ONLY IS EVER REVISITED, two mechanisms beat the one costed above:
  #   - DIRECT VPC EGRESS (network_interfaces) rather than a connector. GA, no
  #     separate resource, no 2–3 instance ceiling, scales with the service. It
  #     is strictly the better MECHANISM — but it still needs ALL_TRAFFIC and so
  #     carries the identical Auth0 coupling. Better plumbing, same risk.
  #   - PSC + a private DNS zone for run.app, which resolves this service to an
  #     internal IP reachable under PRIVATE_RANGES_ONLY and so leaves Auth0 on
  #     its current path — the only option that dodges the coupling. It overrides
  #     DNS for EVERY run.app name in the VPC, cm-backend included, and is
  #     several new resources. Real, and over-engineered for this.
  #
  # THE VIOLATION SIGNATURE, recorded because not knowing it is what made this
  # expensive: INTERNAL_ONLY rejects at the edge with **404, not 403** —
  # deliberately, so it does not reveal that the service exists — and logs at
  # NEITHER end. No request log on the BFF, no error on the caller. That is
  # indistinguishable from "the app never called", which is why the container,
  # then the build, then the environment were all searched before the network.
  ingress = "INGRESS_TRAFFIC_ALL"

  client         = var.client
  client_version = var.client_version

  # The service-level scaling block (distinct from template.scaling above) is
  # re-materialized by the Cloud Run v2 API on every read with zeros that mean
  # "absent". Declaring nothing produces a perpetual diff; ignoring it is the
  # only convergent posture. Template-level min/max instances are unaffected.
  lifecycle {
    ignore_changes = [scaling]
  }

  # THE ORDERING IS NOT INFERRED, BECAUSE NOTHING HERE REFERENCES THE GRANT.
  # The env blocks below read data.google_secret_manager_secret.*.secret_id, which
  # is the DATA SOURCE. Terraform therefore sees an edge to the data source and no
  # edge at all to the iam_member, so it is free to create the revision before the
  # grant exists or propagates, and the container fails to read its own credential.
  # The reader has never hit this only because its grant predated this resource.
  #
  # EVERY iam_member IN THIS MODULE MUST BE LISTED, and the list is checked by
  # tests/test_deployment_posture.py::test_every_secret_iam_member_is_a_depends_on
  # rather than by a reader remembering. A secret added with its grant and without
  # this line produces a revision that starts before it can read its own DSN,
  # which on this service means a failed health check rather than a degradation.
  depends_on = [
    google_secret_manager_secret_iam_member.reader_url,
    google_secret_manager_secret_iam_member.lifecycle_url,
    google_secret_manager_secret_iam_member.provisioner_url,
    google_secret_manager_secret_iam_member.axon_reader_url,
    google_pubsub_topic_iam_member.axon_send_publisher,
  ]

  template {
    service_account = google_service_account.synapse_ui_server.email

    vpc_access {
      connector = var.vpc_connector_id
      egress    = "PRIVATE_RANGES_ONLY"
    }

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      # dis-rls refuses any database but its expected one, defaulting to the
      # pre-consolidation ithina_dis_db which no longer exists.
      env {
        name  = "DIS_EXPECTED_DATABASE"
        value = var.dis_expected_database
      }

      env {
        name  = "SYNAPSE_JWT_ISSUER"
        value = var.jwt_issuer
      }

      env {
        name  = "SYNAPSE_JWT_AUDIENCE"
        value = var.jwt_audience
      }

      # THE FIRST OF TWO database credentials. This said "the ONLY database
      # credential this service is given" until slice 5d added the lifecycle DSN
      # below, which would have made it false the moment the block landed. There
      # is still deliberately no SYNAPSE_WRITER_URL block; the service refuses to
      # start if one appears.
      env {
        name = "SYNAPSE_READER_URL"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.reader_url.secret_id
            version = "latest"
          }
        }
      }

      # The SECOND, added by slice 5d and UNWIRED FOR TWO DAYS: the service has
      # refused to start without it since that slice, which is why v6 and v7 both
      # failed health check and staging kept serving v5. synapse_lifecycle can
      # INSERT on synapse.action_events and nothing else, so the console can
      # record a snooze, dismissal or acknowledgement WITHOUT being able to write
      # synapse.actions, which is the orchestrator's table via synapse_writer.
      #
      # THIS COMMENT SAID "The SECOND and last". It was wrong within one slice, and
      # it is left corrected rather than deleted: "and last" was a prediction about
      # future slices dressed as a fact about this file.
      env {
        name = "SYNAPSE_LIFECYCLE_URL"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.lifecycle_url.secret_id
            version = "latest"
          }
        }
      }

      # The THIRD (slice 5e). synapse_provisioner can INSERT on synapse.provision
      # and SELECT the two tables the enablement pre-flight reads, and nothing
      # else. NO UPDATE anywhere, which is what makes "the console cannot disable a
      # tenant or edit a timezone" a property of the grant rather than of the code:
      # synapse.provision holds one enablement window per (tenant, analysis), so
      # re-enabling would overwrite it and silently corrupt the attribution
      # denominator for the gap.
      #
      # The service refuses to start without this, like the two above.
      env {
        name = "SYNAPSE_PROVISION_URL"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.provisioner_url.secret_id
            version = "latest"
          }
        }
      }

      # THE PROJECT HOLDING axon-send-requested. Not a topic name: the topic's
      # name lives in axon.envelope because both the producer and the consumer
      # need it, and a name configured twice is a name that can disagree with
      # itself. The project is genuinely per-environment; the topic is not.
      #
      # The service refuses to start without it, like the DSNs above.
      env {
        name  = "AXON_PROJECT_ID"
        value = var.project_id
      }

      # THE FIFTH DSN, AND IT IS THE FOURTH'S OPPOSITE (Axon slice 3). axon_reader
      # holds SELECT on both ledgers and NO write verb anywhere. The console's
      # delivery surface reads through it; nothing writes through it.
      #
      # TWO AXON DSNs ON ONE SERVICE IS THE POINT, NOT AN OVERSIGHT. The sender
      # cannot read what it writes and the reader cannot edit what it displays,
      # and both facts are properties of the GRANT rather than of the code.
      #
      # The service refuses to start without it, like the four above.
      env {
        name = "AXON_READER_URL"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.axon_reader_url.secret_id
            version = "latest"
          }
        }
      }

      # NOT A CREDENTIAL, AND STILL REQUIRED. The on-call address is where internal
      # platform events land, and it is the RECIPIENT this service puts on the
      # envelope. The from-address moved to axon-sender with the provider call.
      env {
        name  = "AXON_PLATFORM_ONCALL_EMAIL"
        value = var.axon_platform_oncall_email
      }

      # NOT A CREDENTIAL, AND STILL REQUIRED (slice 5e). Provisioning is gated on
      # the Customer Master permission ADMIN.TENANTS.CONFIGURE.GLOBAL, checked
      # server-side against CM's /api/v1/me/can-do with the CALLER'S OWN Auth0
      # token forwarded. Synapse defines no permission, stores no grant and holds
      # no copy of CM's model; it asks the system that owns the question.
      #
      # THE GATE FAILS CLOSED, so an unreachable or misconfigured CM denies every
      # enable rather than allowing them. That makes a wrong value here a visible
      # refusal instead of an open door, which is the right direction, but it also
      # means the value is load-bearing: staging passes module.cm_service.service_url
      # BY REFERENCE so it cannot drift from the service it names.
      #
      # THIS SERVICE REACHES CM OVER THE PUBLIC INTERNET, and that is already how it
      # works rather than something new: vpc_access egress is PRIVATE_RANGES_ONLY,
      # so only RFC1918 traffic takes the connector and everything else goes direct.
      # The Auth0 JWKS fetch on every cold start proves the path.
      env {
        name  = "CM_API_BASE_URL"
        value = var.cm_api_base_url
      }
    }
  }
}

# See the header. This grants invoke to the DEFAULT COMPUTE identity because that
# is what cm-frontend runs as — which means every default-compute workload in the
# project, not cm-frontend alone.
resource "google_cloud_run_v2_service_iam_member" "frontend_invoker" {
  project  = var.project_id
  location = google_cloud_run_v2_service.synapse_ui_server.location
  name     = google_cloud_run_v2_service.synapse_ui_server.name
  role     = "roles/run.invoker"
  member   = "serviceAccount:${var.caller_service_account_email}"

  # THE REPLACEMENT FOR INGRESS, AND IT IS CHECKED RATHER THAN WRITTEN DOWN.
  #
  # Ingress used to fail closed if somebody added an anonymous invoker binding.
  # It is gone (see the header), so this asserts the same property directly and
  # at the only moment that matters: terraform plan REFUSES, before apply.
  #
  # It reads the INTERPOLATED member string — the value actually sent to the API
  # — not the variable, so a caller email of "allUsers" or any construction that
  # renders to one is caught. Assert the artifact, not the intent: the same
  # standard as the Dockerfile resolving $ASGI_TARGET through uvicorn's own
  # importer, and the build refusing a prerendered console.
  #
  # THERE ARE THREE WAYS IN AND THEY NEED DIFFERENT CHECKS. Each of the two
  # blocks below was verified against real terraform in a provider-free harness
  # (terraform_data + lifecycle), because which one fires AT PLAN and which only
  # at APPLY is a property of value-knownness, not of intent — and the first
  # version of this guard was written as a postcondition that silently deferred:
  #
  #   1. var.caller_service_account_email is set to an anonymous principal.
  #      -> the PRECONDITION below. Proven to refuse at PLAN.
  #   2. the member line here is EDITED to a literal ("allUsers"), bypassing the
  #      variable entirely. The precondition cannot see this: it evaluates its
  #      own expression, not the resource's attribute. That gap was found by
  #      testing the guard, not by reading it.
  #      -> the POSTCONDITION below, which reads self.member — the value actually
  #      sent to the API. Refuses at plan when the value is known, at apply
  #      otherwise; either way the binding is never created.
  #   3. a SECOND iam_member resource is added elsewhere in this module.
  #      Neither block above is on its path.
  #      -> tests/test_deployment_posture.py, which greps the whole file.
  lifecycle {
    precondition {
      condition = !contains(
        ["allUsers", "allAuthenticatedUsers"],
        trimprefix(trimprefix(var.caller_service_account_email, "serviceAccount:"), "user:")
      )
      error_message = <<-EOT
        synapse-ui-server would be granted roles/run.invoker to an ANONYMOUS principal.

        This service has ingress = INGRESS_TRAFFIC_ALL, so IAM is the only network-layer
        control. allUsers/allAuthenticatedUsers here makes it publicly invocable and
        reproduces the standing HIGH finding that every other HTTP service in this estate
        carries. The Auth0 PLATFORM check in auth.py is NOT a substitute: it is a check on
        the person, not on whether the service should be reachable at all.

        If public invocation is genuinely wanted, remove this precondition in its own
        commit with the reason, so the decision is visible in a diff.
      EOT
    }

    # ASSERTS THE ARTIFACT. self.member is the string this resource actually sends,
    # so this holds however the value got there — variable, literal, local or
    # interpolation. The precondition above is the earlier, friendlier gate; this
    # is the one that cannot be routed around.
    postcondition {
      condition = !contains(
        ["allUsers", "allAuthenticatedUsers"],
        trimprefix(trimprefix(self.member, "serviceAccount:"), "user:")
      )
      error_message = <<-EOT
        synapse-ui-server's invoker binding resolved to an ANONYMOUS principal.

        This reads the member string as applied, so it fired even though the precondition
        did not — meaning the value did not come through var.caller_service_account_email.
        Check for a hardcoded member on google_cloud_run_v2_service_iam_member.frontend_invoker.

        Ingress is INGRESS_TRAFFIC_ALL; IAM is the only network-layer control this service has.
      EOT
    }
  }
}
