"""Response models for the Auth0 provisioning actions (Slice 2c).

Both actions are Auth0-side only (D-39): they report what was provisioned in
Auth0 and never imply a CM DB write. ``created`` / ``user_created`` distinguish
a fresh create from an idempotent get (natural-key lookup-before-create).
"""
from uuid import UUID

from pydantic import BaseModel, ConfigDict


class TenantOrgProvisionResult(BaseModel):
    """Result of POST /tenants/{tenant_id}/provision-auth0."""

    model_config = ConfigDict(extra="forbid")

    tenant_id: UUID
    org_id: str
    org_name: str
    created: bool  # True if the Organization was newly created this call


class TenantUserProvisionResult(BaseModel):
    """Result of POST /tenant-users/{user_id}/provision-auth0."""

    model_config = ConfigDict(extra="forbid")

    user_id: UUID  # the CM tenant_users.id (unchanged; 2c writes no DB)
    tenant_id: UUID
    org_id: str
    auth0_user_id: str  # the Auth0 sub; CM persists it only at 2d accept
    user_created: bool  # True if the Auth0 user was newly created this call
