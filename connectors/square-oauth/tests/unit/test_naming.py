"""Secret-id derivation: deterministic, charset-valid, collision-safe."""

from __future__ import annotations

import re
from uuid import UUID

from thalamus_square_oauth.naming import secret_id_for

_TENANT = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")
_SECRET_ID_CHARSET = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


def test_deterministic_for_same_inputs() -> None:
    assert secret_id_for(_TENANT, "square-prod") == secret_id_for(_TENANT, "square-prod")


def test_id_is_valid_secret_manager_charset_and_length() -> None:
    # A pathological 128-char source_id with disallowed characters still yields a valid id.
    source_id = "sq/prod:" + "x" * 200
    secret_id = secret_id_for(_TENANT, source_id)
    assert _SECRET_ID_CHARSET.fullmatch(secret_id) is not None
    assert secret_id.startswith(f"square-oauth-{_TENANT}-")


def test_sanitize_collisions_are_separated_by_hash_suffix() -> None:
    # Both sanitize to the same slug ("a_b"); the raw-source hash suffix keeps them distinct.
    a = secret_id_for(_TENANT, "a/b")
    b = secret_id_for(_TENANT, "a:b")
    assert a != b


def test_different_tenants_never_share_a_secret() -> None:
    other = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
    assert secret_id_for(_TENANT, "s1") != secret_id_for(other, "s1")
