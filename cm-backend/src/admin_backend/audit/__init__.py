"""Audit emission package.

This top-level package is the home for shared audit emission
helpers. The package is intentionally separate from
``repositories/`` (it is not a data-access layer) and from
``routers/`` (it is not request-handling) because the same helpers
are called from both sides: repo methods for success-path emission
inside the data write transaction, the global exception handler for
failure-path emission in a separate transaction.

See ``docs/architecture_audit_logs.md`` for the authoritative
subsystem design.
"""
