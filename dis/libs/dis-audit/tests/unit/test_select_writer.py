"""select_writer refuses to construct a Postgres writer without an engine."""

from __future__ import annotations

import pytest

from dis_audit import AuditBackend, select_writer
from dis_core.errors import AuditWriteError


def test_select_writer_postgres_requires_engine() -> None:
    # No silent fallback for a required value; DisError-rooted, not ValueError.
    with pytest.raises(AuditWriteError):
        select_writer(AuditBackend.POSTGRES)
