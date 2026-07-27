"""Secret-id derivation: deterministic, charset-safe, collision-resistant, Square-congruent."""

from __future__ import annotations

import re
from uuid import UUID

from thalamus_clover_oauth.naming import secret_id_for

_TENANT = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")  # TestCo
_SOURCE = "clover_pos_v1"

# Secret Manager's own constraint.
_LEGAL = re.compile(r"^[A-Za-z0-9_-]{1,255}$")


def test_is_deterministic() -> None:
    assert secret_id_for(_TENANT, _SOURCE) == secret_id_for(_TENANT, _SOURCE)


def test_carries_the_clover_prefix_and_the_tenant() -> None:
    secret_id = secret_id_for(_TENANT, _SOURCE)
    assert secret_id.startswith("clover-oauth-")
    assert str(_TENANT) in secret_id


def test_is_a_legal_secret_id_even_for_a_hostile_source_id() -> None:
    hostile = "a/b c:d.e@f" + "x" * 200
    secret_id = secret_id_for(_TENANT, hostile)
    assert _LEGAL.match(secret_id), secret_id
    assert len(secret_id) <= 255


def test_sources_that_sanitise_alike_do_not_collide() -> None:
    # "a/b" and "a c" both sanitise to "a_b"/"a_c"-style slugs; the raw-source hash is what
    # keeps two different sources off one secret.
    assert secret_id_for(_TENANT, "a/b") != secret_id_for(_TENANT, "a:b")


def test_differs_per_tenant() -> None:
    other = UUID("019e5e3c-b5d3-705f-9002-2451c4ca2626")
    assert secret_id_for(_TENANT, _SOURCE) != secret_id_for(other, _SOURCE)


def test_shape_is_congruent_with_the_square_scheme() -> None:
    # D6: same shape, different prefix — an operator reading a secret list parses either
    # without learning a second convention.
    parts = secret_id_for(_TENANT, _SOURCE).split("-")
    assert parts[0] == "clover"
    assert parts[1] == "oauth"
    assert "-".join(parts[2:7]) == str(_TENANT)  # the UUID's own five dash-separated groups
    assert parts[-2] == "clover_pos_v1"
    assert len(parts[-1]) == 8  # the sha1 prefix
