"""Configuration, read once at startup. Fail at boot, never at the first message.

Every value is required, so a misconfigured revision refuses to become ready rather than pulling
messages it cannot send and nacking them until they dead-letter. That failure would look exactly
like a provider outage from the DLQ, which is the worst place to be told about a typo.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Final

__all__ = ["Config", "load_config"]

# The subscription this service drains. NOT configurable, and that is deliberate: the topic name
# lives in axon.envelope because both sides need it, and a subscription whose name can drift per
# environment is a subscription somebody eventually points at the wrong queue.
SUBSCRIPTION: Final[str] = "axon-send-requested-sub"


@dataclass(frozen=True)
class Config:
    """What the sender needs to drain one message. Frozen: nothing rereads the environment."""

    project_id: str
    # The axon_sender DSN: INSERT on axon.platform_deliveries and NOTHING else. No SELECT
    # anywhere, which is why the ledger write uses neither RETURNING nor ON CONFLICT.
    sender_url: str
    sendgrid_api_key: str
    sendgrid_from_email: str
    expected_database: str
    # Cloud Run injects PORT and a container that hardcodes one fails to start when it is not
    # 8080. Read here so the health server binds what the platform actually gave it.
    port: int
    # Serve /healthz alongside the loop. True on Cloud Run, where the startup probe needs an HTTP
    # surface; a bare local run can turn it off and keep a pure loop.
    run_health_server: bool


def load_config() -> Config:
    """Read the environment. Raises ``RuntimeError`` naming every missing variable at once.

    All at once rather than the first: an operator fixing one and redeploying to discover the
    next is three deploys where one would do. Same shape as synapse-ui-server's loader, and the
    same reason.
    """
    wanted = {
        "GOOGLE_CLOUD_PROJECT": "the GCP project holding the subscription, used to build the "
        "subscription path. Cloud Run does not inject this, so it is set explicitly by the "
        "service module",
        "AXON_SENDER_URL": "the axon_sender DSN: INSERT on axon.platform_deliveries and NOTHING "
        "else. No SELECT anywhere, which is why the write path mints no id of its own and uses "
        "neither RETURNING nor ON CONFLICT",
        "AXON_SENDGRID_API_KEY": "Sevyn8's own SendGrid API key, for Sevyn8's own internal "
        "traffic. NOT a tenant credential: tenant traffic is sent by the TENANT under its own "
        "account, and none of that exists yet",
        "AXON_SENDGRID_FROM_EMAIL": "the from-address. It MUST be a SendGrid-VERIFIED sender on "
        "the account or every send is refused per message, at runtime, in a way that reads like "
        "a provider outage",
    }
    found = {name: os.environ.get(name) for name in wanted}
    missing = sorted(name for name, value in found.items() if not value)
    if missing:
        raise RuntimeError(
            "axon-sender cannot start; missing " + ", ".join(f"{name} ({wanted[name]})" for name in missing)
        )

    # REFUSED, NOT IGNORED. That is the READER's credential (SELECT on both ledgers). A sender
    # holding it could read back a ledger of who was contacted about what, which is exactly the
    # exposure the read-nothing design buys. The grant is the wall; this is the sign on it.
    if os.environ.get("AXON_READER_URL"):
        raise RuntimeError(
            "AXON_READER_URL is set on axon-sender. That is the READ credential (SELECT on both "
            "delivery ledgers); this service writes one table and reads nothing. Either the wrong "
            "variable was configured, or somebody reached for the reader when the sender is what "
            "this process is allowed to be"
        )

    return Config(
        project_id=str(found["GOOGLE_CLOUD_PROJECT"]),
        sender_url=str(found["AXON_SENDER_URL"]),
        sendgrid_api_key=str(found["AXON_SENDGRID_API_KEY"]),
        sendgrid_from_email=str(found["AXON_SENDGRID_FROM_EMAIL"]),
        # dis-rls refuses any database but its expected one, defaulting to the pre-consolidation
        # ithina_dis_db which no longer exists. Set explicitly, as every service here does.
        expected_database=os.environ.get("DIS_EXPECTED_DATABASE", "thalamus"),
        port=int(os.environ.get("PORT", "8080")),
        run_health_server=os.environ.get("RUN_HEALTH_SERVER", "").lower() == "true",
    )
