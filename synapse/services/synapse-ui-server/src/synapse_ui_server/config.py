"""Configuration, read once at startup. A reader DSN, and one narrowly-scoped write DSN.

FAIL AT STARTUP, NOT AT FIRST REQUEST. Every value this service needs is required, so a
misconfigured revision refuses to become ready rather than serving 500s to a console that then
looks broken rather than unconfigured.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

__all__ = ["Config", "load_config"]

# The Auth0 claim namespace Customer Master's Action already stamps. cm-frontend reads the same
# prefix in lib/auth/jwt-decode.ts; both sides must agree or every token looks tenant-less.
CLAIM_NAMESPACE: Final[str] = "https://sevyn8.com/"


@dataclass(frozen=True)
class Config:
    """What the service needs to serve a request. Frozen: nothing rereads the environment.

    THIS SERVICE WAS READ-ONLY UNTIL SLICE 5d, AND EACH WRITE PATH HAS BEEN A DELIBERATE ACT,
    which is exactly what the old comment here demanded ("Slice 8b adds one deliberately"). Two
    have now arrived, 5d and 5e, and each cost an edit to this file. The contract was never
    "never write"; it was "cannot write by accident", and it is still that.

    WHAT KEEPS IT NARROW IS THE GRANT, NOT THE CODE. There are now TWO write credentials and
    each is one verb on one table:

      ``lifecycle_url``    ``synapse_lifecycle``: INSERT on ``synapse.action_events``. Alert
                           decisions. Slice 5d.
      ``provision_url``    ``synapse_provisioner``: INSERT on ``synapse.provision``, plus the two
                           SELECTs its pre-flight cannot run without (identity_mirror.tenants and
                           canonical.store_sku_current_position). Enablement. Slice 5e.

    NEITHER CAN DO THE OTHER'S JOB, and neither can UPDATE or DELETE anything. The provisioner
    in particular has no UPDATE on its own table, so the console cannot disable a tenant or edit
    a timezone: enablement is one direction at the database, not by convention. See
    infra/db-setup/sql/05_synapse_provisioner_grant.sql.

    ``SYNAPSE_WRITER_URL`` IS STILL REFUSED AT STARTUP. That is the ORCHESTRATOR's credential
    (INSERT on synapse.actions), and a console holding it could append to the action log — which
    would make every row ambiguous about whether a human or the 04:00 sweep produced it. The
    refusal did not go away; it got more specific, twice.

    ``cm_api_base_url`` IS NOT A DATABASE THING and it is required all the same. Provisioning is
    gated on a Customer Master permission checked server-side against CM's ``/me/can-do``, so a
    revision without it could not evaluate the gate. A service that cannot check its own
    authorization must not start; the alternative is one that fails open or 500s on every enable.
    """

    reader_url: str
    lifecycle_url: str
    provision_url: str
    cm_api_base_url: str
    jwt_issuer: str
    jwt_audience: str
    expected_database: str
    # AXON (slice 1). Four values, and each is REQUIRED for the same reason the DSNs are: a
    # revision missing any of them has a delivery plane that silently carries nothing, and a
    # delivery plane nobody can tell is dead is worse than no delivery plane.
    #
    # Slice 5d is why this is not an optional block. It shipped an env var this module required
    # and the Terraform module never wired, and the service refused to start behind a green
    # apply for two days while staging kept serving the previous revision. The fix was the
    # wiring, not a softer requirement.
    axon_sender_url: str
    axon_sendgrid_api_key: str
    axon_sendgrid_from_email: str
    axon_platform_oncall_email: str

    @property
    def jwks_url(self) -> str:
        """Derived, never configured separately: a JWKS URL that disagrees with the issuer is a
        misconfiguration that verifies tokens from the wrong tenant of the wrong directory."""
        return f"{self.jwt_issuer.rstrip('/')}/.well-known/jwks.json"


def load_config() -> Config:
    """Read the environment. Raises ``RuntimeError`` naming every missing variable at once.

    All at once rather than the first: an operator fixing one and redeploying to discover the
    next is three deploys where one would do.
    """
    wanted = {
        "SYNAPSE_READER_URL": "the synapse_reader DSN — SELECT on two canonical tables, "
        "synapse.actions, synapse.provision and synapse.run, and no write anywhere",
        "SYNAPSE_LIFECYCLE_URL": "the synapse_lifecycle DSN — INSERT on "
        "synapse.action_events and NOTHING else; not synapse_writer, which is the "
        "orchestrator's and is refused below",
        "SYNAPSE_PROVISION_URL": "the synapse_provisioner DSN: INSERT on "
        "synapse.provision plus SELECT on identity_mirror.tenants and "
        "canonical.store_sku_current_position for the pre-flight, and nothing else. No "
        "UPDATE, so the console cannot disable a tenant or edit a timezone",
        "CM_API_BASE_URL": "Customer Master's origin, e.g. https://cm-backend-<hash>.run.app. "
        "Provisioning is gated on ADMIN.TENANTS.CONFIGURE.GLOBAL, checked against CM's "
        "/api/v1/me/can-do. No trailing slash",
        "SYNAPSE_JWT_ISSUER": "the Auth0 issuer, e.g. https://<tenant>.auth0.com/",
        "SYNAPSE_JWT_AUDIENCE": "the API identifier this service accepts tokens for",
        "AXON_SENDER_URL": "the axon_sender DSN: INSERT on axon.platform_deliveries and "
        "NOTHING else. No SELECT anywhere, which is why the write path mints its own id and "
        "uses neither RETURNING nor ON CONFLICT",
        "AXON_SENDGRID_API_KEY": "Sevyn8's own SendGrid API key, for Sevyn8's own internal "
        "traffic. NOT a tenant credential: tenant traffic is sent by the TENANT under its own "
        "account, and none of that exists yet",
        "AXON_SENDGRID_FROM_EMAIL": "the from-address. It MUST be a SendGrid-VERIFIED sender "
        "on the account or every send is refused per message, at runtime, in a way that reads "
        "like a provider outage",
        "AXON_PLATFORM_ONCALL_EMAIL": "where internal platform alerts go. A LIST, NOT A "
        "PERSON: a personal address breaks when one of three people is away. Same argument as "
        "monitoring-alerts' alert_email, which this deliberately does not reuse - that module "
        "carries facts about PROCESSES and stays outside the system it watches; Axon carries "
        "facts about the DOMAIN",
    }
    found = {name: os.environ.get(name) for name in wanted}
    missing = sorted(name for name, value in found.items() if not value)
    if missing:
        raise RuntimeError(
            "synapse-ui-server cannot start; missing "
            + ", ".join(f"{name} ({wanted[name]})" for name in missing)
        )

    if os.environ.get("SYNAPSE_WRITER_URL"):
        # STILL REFUSED, AND THE REASON SHARPENS EACH TIME A WRITE PATH ARRIVES. This is the
        # orchestrator's credential: INSERT on synapse.actions. Slice 5d gave this service a
        # write path and slice 5e gave it a second, but both are SMALL and NAMED:
        # synapse_lifecycle on synapse.action_events, synapse_provisioner on synapse.provision.
        # A console holding the orchestrator's identity could append to the action log itself,
        # and every row would stop being attributable to the process that caused it.
        #
        # THE NUMBER OF WRITE CREDENTIALS GOING FROM ONE TO TWO IS NOT AN ARGUMENT FOR RELAXING
        # THIS. It is the argument for keeping it: each credential is one verb on one table, and
        # the writer is neither.
        #
        # Kept as a startup refusal rather than left to the grant because it is cheap and it
        # names the mistake. The grant is the wall; this is the sign on it.
        raise RuntimeError(
            "SYNAPSE_WRITER_URL is set on synapse-ui-server. That is the ORCHESTRATOR's "
            "credential (INSERT on synapse.actions); this service writes only "
            "synapse.action_events as synapse_lifecycle and synapse.provision as "
            "synapse_provisioner, via SYNAPSE_LIFECYCLE_URL and SYNAPSE_PROVISION_URL. "
            "Either the wrong variable was configured, or somebody reached for the writer when "
            "one of the two narrow roles is what the console is allowed to be"
        )

    return Config(
        reader_url=str(found["SYNAPSE_READER_URL"]),
        lifecycle_url=str(found["SYNAPSE_LIFECYCLE_URL"]),
        provision_url=str(found["SYNAPSE_PROVISION_URL"]),
        # rstrip("/") HERE, ONCE, rather than at the call site. The variable is written by hand
        # into terraform and a trailing slash would produce "…//api/v1/me/can-do", which Cloud
        # Run answers with a 404 that reads like a missing endpoint rather than a typo.
        cm_api_base_url=str(found["CM_API_BASE_URL"]).rstrip("/"),
        axon_sender_url=str(found["AXON_SENDER_URL"]),
        axon_sendgrid_api_key=str(found["AXON_SENDGRID_API_KEY"]),
        axon_sendgrid_from_email=str(found["AXON_SENDGRID_FROM_EMAIL"]),
        axon_platform_oncall_email=str(found["AXON_PLATFORM_ONCALL_EMAIL"]),
        jwt_issuer=str(found["SYNAPSE_JWT_ISSUER"]),
        jwt_audience=str(found["SYNAPSE_JWT_AUDIENCE"]),
        # dis-rls refuses any database but its expected one, defaulting to the pre-consolidation
        # ithina_dis_db which no longer exists. Set explicitly, as every service here does.
        expected_database=os.environ.get("DIS_EXPECTED_DATABASE", "thalamus"),
    )
