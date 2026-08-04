"""Synapse — the Thalamus analytics + actions plane.

A PEER of DIS, not part of it: separate deploy, separate lifecycle, its own root
package. It reads canonical READ-ONLY and (later) emits actions. It never writes a
DIS table.

Layering, enforced rather than described:

- ``synapse.core`` — pure types. No database, no SQL, no canonical row shapes.
- ``synapse.resolvers`` — the ONLY package that may reach a canonical table.
- ``synapse.registry`` — binds capability ids to resolvers and answers "can this be
  satisfied for THIS tenant right now". Composes resolvers; reaches no database itself.

WHAT IMPORT-LINTER ACTUALLY ENFORCES, stated exactly, because the previous version of
this paragraph overstated it. Three contracts in dis/pyproject.toml:

- ``synapse.core`` may not import ``dis_canonical``, ``dis_rls``, ``sqlalchemy`` or
  ``psycopg`` — directly or transitively.
- ``synapse.registry`` may not import ``dis_canonical``, ``dis_rls`` or ``psycopg``
  DIRECTLY. Transitively it must, since it binds resolvers that use them.
- A ``layers`` contract fixes the order ``registry > resolvers > core``, so core cannot
  import upward and a resolver cannot reach back into the registry.

This file used to say the trio was forbidden to "every ``synapse.*`` module except
``synapse.resolvers``". It never was — the contracts named ``synapse.core`` alone — and
the overclaim would have mattered the moment ``synapse.registry`` arrived outside the
enforced set. The layers contract is what generalises the rule for real.

A grep test remains the mechanism for the table-NAME half, because a table name is a
string literal and no import graph can see one.
"""
