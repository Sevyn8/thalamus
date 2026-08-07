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

    THIS SERVICE WAS READ-ONLY UNTIL SLICE 5d, AND THE CHANGE WAS A DELIBERATE ACT — which is
    exactly what the old comment here demanded ("Slice 8b adds one deliberately"). The contract
    was never "never write"; it was "cannot write by accident", and it is still that.

    WHAT KEEPS IT NARROW IS THE GRANT, NOT THE CODE. ``lifecycle_url`` is a THIRD role,
    ``synapse_lifecycle``, holding INSERT on ``synapse.action_events`` and nothing else — no
    SELECT, no UPDATE, no DELETE, no other table. So the blast radius of this service being
    wrong is one append to one table, enforced by Postgres rather than by review.

    ``SYNAPSE_WRITER_URL`` IS STILL REFUSED AT STARTUP. That is the ORCHESTRATOR's credential
    (INSERT on synapse.actions), and a console holding it could append to the action log — which
    would make every row ambiguous about whether a human or the 04:00 sweep produced it. The
    refusal did not go away; it got more specific.
    """

    reader_url: str
    lifecycle_url: str
    jwt_issuer: str
    jwt_audience: str
    expected_database: str

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
        "SYNAPSE_JWT_ISSUER": "the Auth0 issuer, e.g. https://<tenant>.auth0.com/",
        "SYNAPSE_JWT_AUDIENCE": "the API identifier this service accepts tokens for",
    }
    found = {name: os.environ.get(name) for name in wanted}
    missing = sorted(name for name, value in found.items() if not value)
    if missing:
        raise RuntimeError(
            "synapse-ui-server cannot start; missing "
            + ", ".join(f"{name} ({wanted[name]})" for name in missing)
        )

    if os.environ.get("SYNAPSE_WRITER_URL"):
        # STILL REFUSED, AND NOW FOR A SHARPER REASON. This is the orchestrator's credential:
        # INSERT on synapse.actions. Slice 5d gave this service a write path, but a DIFFERENT
        # and much smaller one — synapse_lifecycle, INSERT on synapse.action_events alone. A
        # console holding the orchestrator's identity could append to the action log itself,
        # and every row would stop being attributable to the process that caused it.
        #
        # Kept as a startup refusal rather than left to the grant because it is cheap and it
        # names the mistake. The grant is the wall; this is the sign on it.
        raise RuntimeError(
            "SYNAPSE_WRITER_URL is set on synapse-ui-server. That is the ORCHESTRATOR's "
            "credential (INSERT on synapse.actions); this service writes only "
            "synapse.action_events and does so as synapse_lifecycle via SYNAPSE_LIFECYCLE_URL. "
            "Either the wrong variable was configured, or somebody reached for the writer when "
            "the lifecycle role is what the console is allowed to be"
        )

    return Config(
        reader_url=str(found["SYNAPSE_READER_URL"]),
        lifecycle_url=str(found["SYNAPSE_LIFECYCLE_URL"]),
        jwt_issuer=str(found["SYNAPSE_JWT_ISSUER"]),
        jwt_audience=str(found["SYNAPSE_JWT_AUDIENCE"]),
        # dis-rls refuses any database but its expected one, defaulting to the pre-consolidation
        # ithina_dis_db which no longer exists. Set explicitly, as every service here does.
        expected_database=os.environ.get("DIS_EXPECTED_DATABASE", "thalamus"),
    )
