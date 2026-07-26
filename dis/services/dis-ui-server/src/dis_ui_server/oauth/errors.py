"""BFF-local OAuth errors (DisError subclasses), mapped to HTTP by ``errors_http``.

Defined here rather than in dis-core: they are specific to this service's Square connect
flow, and ``errors_http._STATUS_BY_ERROR`` maps them without any dis-core edit. None of them
carry token or secret material (contract: domain errors are PII/credential-free).

Naming: these classes use ``Oauth`` (not ``OAuth``) deliberately. ``errors_http._code_for``
derives the wire ``code`` by splitting on capital letters, so ``OAuth`` would emit the
awkward ``o_auth_...``; ``Oauth`` yields the clean ``oauth_not_configured`` /
``invalid_oauth_state`` / ``oauth_state_tenant_mismatch`` codes the S3 frontend reads.
"""

from __future__ import annotations

from dis_core.errors import DisError


class OauthNotConfiguredError(DisError):
    """The Square OAuth endpoints were called but the server has no OAuth config (503)."""

    def __init__(self, message: str, *, connector: str) -> None:
        super().__init__(message)
        self.message = message
        self.connector = connector


class InvalidOauthStateError(DisError):
    """The ``state`` token failed signature/expiry/shape validation (422)."""

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.message = message
        self.reason = reason


class OauthStateTenantMismatchError(DisError):
    """The state's tenant does not match the authenticated caller's tenant (403)."""


class SquareTokenExchangeError(DisError):
    """Square rejected or failed the authorization-code exchange (502). No vendor detail is
    carried into the client response by construction."""
