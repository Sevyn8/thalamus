###############################################################################
# synapse-ui-server: the read-only BFF behind Synapse's superadmin console.
#
# Called SERVER-SIDE by cm-frontend's Next.js server components. The browser
# never reaches it, so it needs no public invoker binding and no CORS.
#
# READ-ONLY, AND THE CREDENTIAL SAYS SO. It is given the synapse_reader DSN and
# nothing else — no writer secret is granted, no writer env var is set, and the
# service refuses to START if SYNAPSE_WRITER_URL is present. Slice 8b needs a
# writer for provisioning and must add it deliberately rather than find it
# already wired.
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
#   - No secretAccessor on any writer DSN. There is no write path to serve.
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

      # The ONLY database credential this service is given. There is deliberately
      # no SYNAPSE_WRITER_URL block; the service refuses to start if one appears.
      env {
        name = "SYNAPSE_READER_URL"
        value_source {
          secret_key_ref {
            secret  = data.google_secret_manager_secret.reader_url.secret_id
            version = "latest"
          }
        }
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
