"""Pure Synapse types. NO database, NO SQL, NO canonical row shapes.

This package must stay importable with nothing installed but pydantic-free stdlib
plus the type-only imports it declares. import-linter enforces that: ``dis_canonical``,
``dis_rls``, ``sqlalchemy`` and ``psycopg`` are forbidden here — directly AND
transitively — so a stray convenience import fails the lint rather than quietly making
the pure layer database-aware. A ``layers`` contract additionally forbids this package
from importing ``synapse.resolvers`` or ``synapse.registry``, which is the transitive
route a "just this once" helper import would take.

THE FORBIDDEN-IMPORT CONTRACTS COVER ``synapse.core``, NOT "everything but resolvers";
the wider rule is real, but it is the layers contract that carries it — see
dis/pyproject.toml.

THE GATE SPLIT IS THREE-WAY. ``core.capability`` declares which gate KINDS a capability
can be measured on; ``core.analysis`` carries the THRESHOLD and the POLICY, because those
belong to whoever is asking; and the MEASUREMENT is a database read that names a canonical
table, so it lives in ``synapse.resolvers`` — a probe placed here would fail the lint
above, which is why that third part is a mechanism rather than a convention.
"""
