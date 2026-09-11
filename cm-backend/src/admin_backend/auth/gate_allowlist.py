"""Mandatory-gate-discipline allowlist.

Endpoints listed in ``GATE_EXEMPT_PATHS`` are explicitly exempt from
RBAC gating. They require authentication (via ``AuthMiddleware``) but
have no permission gate. The mandatory-gate-discipline test
(``tests/integration/test_gate_discipline.py``) asserts every
``APIRoute`` is either gated (has ``__permission_gate__`` marker on
some dependency) OR is in this set OR is in
``middleware/auth.py::PUBLIC_PATHS``.

Coupling — must stay in sync with two other sets:
  - ``PUBLIC_PATHS`` at ``middleware/auth.py`` (auth-skip layer)
  - Mandatory-gate-discipline test (consumes both sets)

Adding an endpoint without either a gate or an allowlist entry is a
deploy-time error by design — the discipline test fails the build.

v0 exempt set (9 paths):
  - ``/api/v1/me/permissions`` — caller-state; gating against the
    caller's own permission set is circular. Also the hook for implicit
    invite-acceptance reconciliation (a TENANT user's first authenticated
    boot call flips their INVITED row to ACTIVE); the explicit
    accept-invitation endpoint was retired in favour of it.
  - ``/api/v1/me/can-do`` — caller-state, same.
  - ``/api/v1/module-access/me`` — caller-state: the caller's
    OWN tenant's enabled modules, RLS-scoped to the JWT tenant. Powers
    the tenant-persona launcher without an admin governance grant; the
    admin matrix/modules endpoints stay gated on ADMIN.TENANTS.VIEW.TENANT.
  - ``/api/v1/lookups`` — reference data; any authenticated user.
  - ``/api/v1/permissions`` — catalogue; any authenticated user.
  - ``/api/v1/permission-matrix`` — catalogue render-grid; any
    authenticated user.
  - ``/api/v1/roles`` — role catalogue view; any authenticated user.
  - ``/api/v1/roles/{role_id}/permissions`` — same.
  - ``/api/v1/roles/{role_id}`` — role detail. Joins the other role
    read endpoints; PATCH gates on ADMIN.ROLES.OVERRIDE.GLOBAL but GET
    stays exempt (deliberate deferral).

Forward note: revisit gating ``/permissions``,
``/permission-matrix``, ``/roles`` on
``ADMIN.ROLES.VIEW.TENANT`` when further write surfaces land.
``/lookups`` stays exempt regardless.
"""
from __future__ import annotations


GATE_EXEMPT_PATHS: frozenset[str] = frozenset({
    "/api/v1/me/permissions",
    "/api/v1/me/can-do",
    "/api/v1/module-access/me",
    "/api/v1/lookups",
    "/api/v1/permissions",
    "/api/v1/permission-matrix",
    "/api/v1/roles",
    "/api/v1/roles/{role_id}",
    "/api/v1/roles/{role_id}/permissions",
})
