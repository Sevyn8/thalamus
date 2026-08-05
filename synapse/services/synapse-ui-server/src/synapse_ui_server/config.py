"""Configuration, read once at startup. Reader DSN only — there is no writer here.

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

    THERE IS NO ``writer_url`` FIELD, AND ITS ABSENCE IS THE POINT. Slice 8a writes nothing, and
    a service that cannot write is better than one that chooses not to — the same argument that
    made synapse_writer worth separating from synapse_reader. Slice 8b adds one deliberately.
    """

    reader_url: str
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
        # NOT a warning. A writer DSN present in this service's environment means somebody wired
        # one expecting it to be used, and the honest answer is that nothing here can. Failing
        # loudly beats a credential sitting unused in a revision's environment.
        raise RuntimeError(
            "SYNAPSE_WRITER_URL is set on synapse-ui-server, which holds no write path at all "
            "(slice 8a is read-only). Either the wrong service was configured, or a write path "
            "was added without removing this check — and the check is what makes 'cannot write' "
            "a property rather than an intention"
        )

    return Config(
        reader_url=str(found["SYNAPSE_READER_URL"]),
        jwt_issuer=str(found["SYNAPSE_JWT_ISSUER"]),
        jwt_audience=str(found["SYNAPSE_JWT_AUDIENCE"]),
        # dis-rls refuses any database but its expected one, defaulting to the pre-consolidation
        # ithina_dis_db which no longer exists. Set explicitly, as every service here does.
        expected_database=os.environ.get("DIS_EXPECTED_DATABASE", "thalamus"),
    )
