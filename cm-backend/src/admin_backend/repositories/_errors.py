"""Shared Repo-layer errors.

These exceptions are raised inside Repo methods (data-access layer)
and caught in routers, where they are re-mapped to HTTP-shaped
``ClientError`` subclasses (see ``admin_backend.errors``).

Lives in its own underscore-prefixed module because every Repo
imports it but it isn't part of the Repo public surface.
"""
from __future__ import annotations


class InvalidSortKeyError(ValueError):
    """Raised when a Repo's ``sort`` argument isn't a recognised key.

    Subclasses ``ValueError`` so legacy callers catching ``ValueError``
    still work; routers catch this specifically and re-raise as a
    typed 400 ``InvalidSortKeyClientError``.
    """
