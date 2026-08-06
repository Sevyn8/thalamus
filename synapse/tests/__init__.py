"""Marks synapse's tests as a package so sibling modules can import the conftest helpers.

WHY THIS EXISTS WHEN MOST TEST DIRS HERE HAVE NO __init__.py. The repo default is deliberate —
dis/Makefile records it: identically-named test modules across libs cannot share one mypy run, so
test dirs stay non-packages. That reasoning is about modules with COLLIDING basenames spread over
several mypy invocations. It does not apply here: `../synapse` is one mypy target and one pytest
invocation, and `services/streaming-consumer/tests/` already carries the same three files for the
same reason (17 `from .conftest import` sites).

WHAT BREAKS WITHOUT IT. pytest runs with --import-mode=importlib, under which a test module cannot
reach a sibling by bare name — `from conftest import x` raises ModuleNotFoundError at COLLECTION,
taking the whole file down. The disposable-database guard has to be imported by the two live write
modules, so it needs a real package to be imported from.
"""
