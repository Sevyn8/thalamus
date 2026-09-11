"""Identity Service client interface.

The single client abstraction that DIS services use to call the Identity Service.
Any implementation (fake or real) is consumed through this interface, satisfying
the same Protocol and HTTP contract as a drop-in — callers swap
``IDENTITY_SERVICE_URL`` and nothing else changes.

Shapes conform to the authoritative contract
``contracts/identity-service/identity_service.openapi.yaml``.
"""

from dis_core.identity.client import (
    HttpIdentityClient,
    IdentityClient,
    IdentityClientError,
    IdentityNotFoundError,
    IdentityServiceUnavailableError,
)
from dis_core.identity.models import (
    Error,
    Identity,
    ResolveFromEndpointRequest,
    ResolveFromTokenRequest,
    ResolveFromUploadRequest,
    ValidateRequest,
    ValidateResponse,
)

__all__ = [
    "Error",
    "HttpIdentityClient",
    "Identity",
    "IdentityClient",
    "IdentityClientError",
    "IdentityNotFoundError",
    "IdentityServiceUnavailableError",
    "ResolveFromEndpointRequest",
    "ResolveFromTokenRequest",
    "ResolveFromUploadRequest",
    "ValidateRequest",
    "ValidateResponse",
]
