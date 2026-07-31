"""Synapse — the Thalamus analytics + actions plane.

A PEER of DIS, not part of it: separate deploy, separate lifecycle, its own root
package. It reads canonical READ-ONLY and (later) emits actions. It never writes a
DIS table.

Layering, enforced rather than described:

- ``synapse.core`` — pure types. No database, no SQL, no canonical row shapes.
- ``synapse.resolvers`` — the ONLY package that may reach a canonical table.

import-linter forbids ``dis_canonical``, ``dis_rls`` and ``sqlalchemy`` to every
``synapse.*`` module except ``synapse.resolvers``; a grep test is the mechanism for
the table-NAME half, because a table name is a string literal and no import graph can
see one.
"""
