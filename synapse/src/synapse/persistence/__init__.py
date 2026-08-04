"""Durable implementations of the action-log protocols. The only package that writes.

``synapse.resolvers`` is the only package that may reach a CANONICAL table; this is the only one
that may write anything at all, and it writes to ``synapse.actions`` — Synapse's own schema in
the shared database, never a DIS-owned table.

Separate from ``synapse.resolvers`` because the two have opposite postures and hold different
database roles: resolvers read canonical as ``synapse_reader`` and construct no write statement;
this package appends as ``synapse_writer``, which holds INSERT and nothing else. Keeping them
apart is what lets each engine carry a role that cannot do the other's job.
"""
