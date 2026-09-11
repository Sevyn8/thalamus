"""Thin FastAPI routers, one per UI sub-module; ``main.py`` mounts them.

The health/liveness probes stay at the root; every other handler (mapping
CRUD, quarantine, audit, canonical, runs, sources, stores, tenants, …)
attaches under the ``/api/v1`` router.
"""
