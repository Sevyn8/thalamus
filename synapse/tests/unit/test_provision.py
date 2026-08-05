"""Provision, the Rung ladder, and the envelope check — the SELECTION side and its boundary.

THE ENVELOPE CHECK IS THE POINT OF MOST OF THIS FILE. "A provision may not exceed its analysis's
declared max_rung" is a safety property, and a safety property that cannot fire is decoration.
So these tests do the thing the fourth guard direction asks for: they construct the ILLEGAL case
and prove it is refused, rather than only confirming that the legal case passes.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from uuid import UUID

import pytest

from synapse.core.analysis import DEAD_STOCK
from synapse.core.errors import ProvisionRefusedError
from synapse.core.provision import Cadence, Provision, Rung, rung_rank
from synapse.persistence.provision_postgres import check_envelope, project

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
ENABLED = datetime(2026, 8, 1, 0, 0, tzinfo=UTC)


def _provision(**overrides: object) -> Provision:
    fields: dict[str, object] = {
        "tenant_id": TENANT,
        "analysis_id": "dead_stock",
        "cadence": Cadence.DAILY,
        "rung": Rung.SHADOW,
        "timezone": "Asia/Kolkata",
        "enabled_at": ENABLED,
    }
    fields.update(overrides)
    return Provision(**fields)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The ladder
# ---------------------------------------------------------------------------


def test_every_rung_is_ranked_and_the_ladder_is_a_total_order() -> None:
    """``_check_ranks`` runs at import; this asserts the property it protects.

    An unranked rung would raise a KeyError inside the comparison, and two rungs sharing a rank
    would make "may not exceed" meaningless in one direction.
    """
    ranks = [rung_rank(rung) for rung in Rung]
    assert len(set(ranks)) == len(ranks)
    assert sorted(ranks) == ranks or sorted(ranks) == sorted(set(ranks))


def test_shadow_is_below_suggest() -> None:
    """The ONE ordering the envelope check depends on. If these ever compared equal, a provision
    asking for delivery would pass a ceiling of shadow."""
    assert rung_rank(Rung.SHADOW) < rung_rank(Rung.SUGGEST)


def test_dead_stock_declares_a_shadow_ceiling() -> None:
    """Not a tautology: it is the assertion that the first analysis has not quietly been given
    room to deliver. Raising it should require editing this test too."""
    assert DEAD_STOCK.max_rung is Rung.SHADOW


# ---------------------------------------------------------------------------
# Provision validation
# ---------------------------------------------------------------------------


def test_a_provision_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        _provision().rung = Rung.SUGGEST  # type: ignore[misc]


def test_a_naive_enabled_at_is_refused() -> None:
    """enabled_at starts an attribution window. An ambiguous instant makes the window ambiguous,
    and the window is the denominator."""
    with pytest.raises(ValueError, match="naive enabled_at"):
        _provision(enabled_at=datetime(2026, 8, 1, 0, 0))


def test_an_unresolvable_timezone_is_refused_in_python_too() -> None:
    """The DDL trigger refuses this at the database. This is the same check for a Provision built
    without touching the table — a test, or a future caller. Both exist because the failure is
    SILENT: a bad zone mis-stamps every as_of rather than failing anything."""
    with pytest.raises(ValueError, match="does not resolve"):
        _provision(timezone="Mars/Olympus_Mons")


def test_an_empty_analysis_id_is_refused() -> None:
    with pytest.raises(ValueError, match="must name an analysis"):
        _provision(analysis_id="")


# ---------------------------------------------------------------------------
# Projection from a row
# ---------------------------------------------------------------------------


def test_a_row_projects_through_the_frozen_type() -> None:
    """Validation happens THROUGH Provision rather than around it, so a row from the database
    gets the same checks as one built in code."""
    provision = project(
        {
            "tenant_id": str(TENANT),
            "analysis_id": "dead_stock",
            "cadence": "daily",
            "rung": "shadow",
            "timezone": "Asia/Kolkata",
            "enabled_at": ENABLED,
        }
    )
    assert provision == _provision()


def test_a_stored_rung_the_enum_does_not_know_raises_at_projection() -> None:
    """The state after a migration widens ck_provision_rung and the code has not caught up. A
    string flowing on would compare unequal to every Rung and silently behave as though the row
    were something else."""
    with pytest.raises(ValueError, match="not a valid Rung"):
        project(
            {
                "tenant_id": str(TENANT),
                "analysis_id": "dead_stock",
                "cadence": "daily",
                "rung": "autonomous",
                "timezone": "Asia/Kolkata",
                "enabled_at": ENABLED,
            }
        )


def test_a_stored_cadence_the_enum_does_not_know_raises_at_projection() -> None:
    with pytest.raises(ValueError, match="not a valid Cadence"):
        project(
            {
                "tenant_id": str(TENANT),
                "analysis_id": "dead_stock",
                "cadence": "hourly",
                "rung": "shadow",
                "timezone": "Asia/Kolkata",
                "enabled_at": ENABLED,
            }
        )


# ---------------------------------------------------------------------------
# The envelope check — proved by constructing the illegal case
# ---------------------------------------------------------------------------


CEILINGS = {"dead_stock": Rung.SHADOW}


def test_a_provision_within_its_ceiling_is_accepted() -> None:
    """The baseline the refusals below are contrasted against. Without it, every assertion in
    this section would also pass against a function that refused everything."""
    check_envelope([_provision(rung=Rung.SHADOW)], CEILINGS)


def test_a_rung_above_the_declared_ceiling_is_refused() -> None:
    """THE ENVELOPE, FIRING. dead_stock declares max_rung=SHADOW; a table row asking for SUGGEST
    is an operator promoting an unvalidated analysis with an UPDATE, which is precisely what the
    code-side ceiling exists to prevent."""
    with pytest.raises(ProvisionRefusedError, match="exceed their analysis"):
        check_envelope([_provision(rung=Rung.SUGGEST)], CEILINGS)


def test_the_refusal_names_the_tenant_the_analysis_and_both_rungs() -> None:
    """An operator reading this in a job log needs to know which row to fix and what the limit
    is. A bare 'provision refused' would send them to the source."""
    with pytest.raises(ProvisionRefusedError) as caught:
        check_envelope([_provision(rung=Rung.SUGGEST)], CEILINGS)
    message = str(caught.value)
    assert str(TENANT) in message
    assert "dead_stock" in message
    assert "suggest" in message and "shadow" in message


def test_an_analysis_no_declaration_claims_is_refused() -> None:
    """A typo in analysis_id would otherwise enable NOTHING while the row looks enabled — the
    tenant is silently never analysed, and the table exists to stop exactly that."""
    with pytest.raises(ProvisionRefusedError, match="no declaration claims"):
        check_envelope([_provision(analysis_id="dead_stok")], CEILINGS)


def test_one_bad_row_refuses_the_whole_enumeration() -> None:
    """Deliberately NOT a filter. Dropping the offending row would let the sweep report success
    while a tenant quietly stopped being analysed."""
    with pytest.raises(ProvisionRefusedError):
        check_envelope([_provision(), _provision(tenant_id=UUID(int=7), rung=Rung.SUGGEST)], CEILINGS)


def test_every_offending_row_is_named_not_just_the_first() -> None:
    """An operator fixing one typo should not have to re-run the sweep to discover the next."""
    other = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a161")
    with pytest.raises(ProvisionRefusedError) as caught:
        check_envelope(
            [_provision(rung=Rung.SUGGEST), _provision(tenant_id=other, rung=Rung.SUGGEST)],
            CEILINGS,
        )
    assert str(TENANT) in str(caught.value)
    assert str(other) in str(caught.value)


def test_an_empty_estate_is_not_an_error() -> None:
    """Nothing provisioned is a legitimate state — it is the state today — and must not raise."""
    check_envelope([], CEILINGS)


# ---------------------------------------------------------------------------
# The DDL vocabularies and the enums must agree
# ---------------------------------------------------------------------------


def _check_values(constraint: str, column: str) -> set[str]:
    """The literals a CHECK ... IN (...) admits, read out of the DDL file."""
    import re
    from pathlib import Path

    sql = (Path(__file__).resolve().parents[2] / "schemas" / "postgres" / "provision.sql").read_text(
        encoding="utf-8"
    )
    match = re.search(rf"{constraint}\s*\n?\s*CHECK \({column} IN \(([^)]*)\)\)", sql)
    assert match, f"{constraint} not found in provision.sql; the guard has lost its target"
    return {literal.strip().strip("'") for literal in match.group(1).split(",")}


def test_the_ddl_rung_vocabulary_matches_the_enum() -> None:
    """TWO SOURCES OF TRUTH THAT MUST AGREE, and nothing else makes them.

    A migration widening ck_provision_rung without adding the member here would let an operator
    store a rung the code cannot construct. ``project`` raises on it — so the failure is loud —
    but it is loud IN PRODUCTION, on a sweep, for one tenant. This is the same disagreement
    caught offline instead.
    """
    assert _check_values("ck_provision_rung", "rung") == {rung.value for rung in Rung}


def test_the_ddl_cadence_vocabulary_matches_the_enum() -> None:
    assert _check_values("ck_provision_cadence", "cadence") == {c.value for c in Cadence}
