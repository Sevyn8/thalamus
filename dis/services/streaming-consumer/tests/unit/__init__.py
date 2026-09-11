"""Package context so the integration conftest helpers import typed under mypy --strict
(per-package gate). Deviates from the no-__init__ test convention; pytest importlib
mode and the per-package mypy run are unaffected.
"""
