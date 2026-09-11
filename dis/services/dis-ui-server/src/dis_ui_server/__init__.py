"""dis-ui-server: the single backend-for-frontend for the DIS UI.

A FastAPI service: liveness/readiness probes, the auth seam (JWT verifier
behind ``get_current_identity`` / ``require_tenant`` / ``require_ops``), the
dis-rls per-tenant session wiring + ORM base, the DisError-to-envelope
exception handlers, structured logging, and the tenant-scoped UI data
endpoints.
"""
