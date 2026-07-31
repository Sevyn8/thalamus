"""Pure Synapse types. NO database, NO SQL, NO canonical row shapes.

This package must stay importable with nothing installed but pydantic-free stdlib
plus the type-only imports it declares. import-linter enforces that: ``dis_rls`` and
``sqlalchemy`` are forbidden here, so a stray convenience import fails the lint
rather than quietly making the pure layer database-aware.

``core.current_state`` imports ``dis_canonical`` for the ``from_canonical``
constructor's type only, which is why the import-linter contract names
``dis_canonical`` separately from the database pair — see the contracts in
dis/pyproject.toml for which is forbidden where.
"""
