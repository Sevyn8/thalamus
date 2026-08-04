"""Actions, provenance, the append-only log, and the dead_stock proposer. All pure.

THE LOAD-BEARING TESTS ARE THE TWO ABOUT WHAT CANNOT BE RETROFITTED:

- an action cannot be built without an arm, and there is no value meaning "not assigned";
- an action cannot be built without complete provenance.

Both are constructor-level rather than review-level, because both are unfixable after the fact.
An action recorded today without an arm is permanently outside any study, and no migration
recovers it.

Plus the append-only property, proved by what the log DOES NOT OFFER rather than asserted.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from synapse.core.action import Action, ActionEvent, Provenance, Verb
from synapse.core.action_log import ActionLog, InMemoryActionLog
from synapse.core.analysis import DEAD_STOCK
from synapse.core.current_state import CurrentStateRow
from synapse.core.dead_stock import DeadStockRow
from synapse.core.dead_stock_actions import propose_dead_stock_actions
from synapse.core.holdout import Arm

TENANT = UUID("019e5e3c-b5d6-7eed-93f9-3778a7a7a160")
STORE = UUID("019e5e3c-b633-7344-93c7-83fb205285ea")
AS_OF = date(2026, 8, 5)
VERSIONS = {"current_state": "0.1.0", "last_sale_at": "0.1.0"}


def _provenance(**overrides: object) -> Provenance:
    base: dict[str, object] = {
        "declaration_id": "dead_stock",
        "declaration_version": "0.1.0",
        "capability_versions": VERSIONS,
        "thresholds": {"stale_after_days": 90},
        "as_of": AS_OF,
    }
    base.update(overrides)
    return Provenance(**base)  # type: ignore[arg-type]


def _action(**overrides: object) -> Action:
    base: dict[str, object] = {
        "target": {"tenant_id": str(TENANT), "store_id": str(STORE), "sku_id": "SKU-1"},
        "verb": Verb.REVIEW,
        "quantity_at_stake": Decimal("40.000"),
        "expires_on": AS_OF + timedelta(days=30),
        "arm": Arm.TREATMENT,
        "provenance": _provenance(),
    }
    base.update(overrides)
    return Action(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The two that cannot be retrofitted
# ---------------------------------------------------------------------------


def test_an_action_cannot_be_built_without_an_arm() -> None:
    """THE UNFIXABLE ONE. An action recorded without an arm is permanently outside any study —
    a control group cannot be constructed backwards — so the field has no default at all."""
    with pytest.raises(TypeError):
        Action(  # type: ignore[call-arg]
            target={"sku_id": "SKU-1"},
            verb=Verb.REVIEW,
            quantity_at_stake=None,
            expires_on=AS_OF,
            provenance=_provenance(),
        )


def test_there_is_no_arm_meaning_not_assigned() -> None:
    assert {arm.value for arm in Arm} == {"treatment", "holdout"}


def test_an_action_cannot_be_built_without_provenance() -> None:
    with pytest.raises(TypeError):
        Action(  # type: ignore[call-arg]
            target={"sku_id": "SKU-1"},
            verb=Verb.REVIEW,
            quantity_at_stake=None,
            expires_on=AS_OF,
            arm=Arm.TREATMENT,
        )


def test_provenance_without_capability_versions_is_refused() -> None:
    """An empty mapping means the resolutions were DROPPED on the way rather than that none
    existed — every declaration requires at least one capability."""
    with pytest.raises(ValueError, match="names no capability versions"):
        _provenance(capability_versions={})


def test_provenance_without_a_declaration_version_is_refused() -> None:
    """Which rule is not enough; an attribution study needs which REVISION of it."""
    with pytest.raises(ValueError, match="and its version"):
        _provenance(declaration_version="")


def test_provenance_records_threshold_values_not_a_reference() -> None:
    """A threshold recorded by name would be re-read later at its NEW value, which is the subtle
    version of comparing two systems as one."""
    provenance = _provenance(thresholds={"stale_after_days": 90})
    assert all(isinstance(value, int) for value in provenance.thresholds.values())


# ---------------------------------------------------------------------------
# The action itself
# ---------------------------------------------------------------------------


def test_only_one_verb_exists() -> None:
    """Restraint, not incompleteness: a markdown needs elasticity, a margin floor and supplier
    return terms, none of which exists anywhere in canonical."""
    assert {verb.value for verb in Verb} == {"review"}


def test_an_unknown_quantity_is_none_and_never_zero() -> None:
    """stock_qty is nullable. Zero would sort a dead position to the bottom of any list built on
    this, which is the wrong end for the thing the list is for."""
    assert _action(quantity_at_stake=None).quantity_at_stake is None


def test_a_negative_quantity_is_refused() -> None:
    with pytest.raises(ValueError, match="negative stock"):
        _action(quantity_at_stake=Decimal("-1"))


def test_an_action_that_expires_before_it_was_evaluated_is_refused() -> None:
    """An action that arrives expired cannot be acted on, and would silently never appear."""
    with pytest.raises(ValueError, match="before the"):
        _action(expires_on=AS_OF - timedelta(days=1))


def test_an_action_with_no_target_is_refused() -> None:
    with pytest.raises(ValueError, match="is a suggestion"):
        _action(target={})


def test_the_action_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        _action().arm = Arm.HOLDOUT  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Append-only
# ---------------------------------------------------------------------------


def test_the_log_offers_no_way_to_edit_or_remove() -> None:
    """APPEND-ONLY PROVED BY ABSENCE, which is the strongest form available without a database.

    A table with a comment saying "do not update" is what canonical's event tables had before
    migration 0019, and it cost one 328-row upload becoming 1640. A type that offers no edit
    cannot be edited by someone in a hurry.
    """
    forbidden = {"update", "delete", "remove", "replace", "clear", "pop", "insert", "extend"}
    for surface in (ActionLog, InMemoryActionLog):
        offered = {name for name in dir(surface) if not name.startswith("_")}
        assert offered & forbidden == set(), f"{surface.__name__} offers {offered & forbidden}"
    assert {name for name in dir(InMemoryActionLog) if not name.startswith("_")} == {
        "append",
        "events",
    }


def test_events_returns_a_copy_so_the_log_cannot_be_appended_through_it() -> None:
    """Returning the live list would make append() advisory and append-only a convention."""
    log = InMemoryActionLog()
    log.append(_event(1))
    snapshot = log.events()
    assert isinstance(snapshot, tuple)
    assert len(log.events()) == 1


def test_a_correction_is_a_new_event_naming_what_it_supersedes() -> None:
    """D33's shape one layer up: an append-only log can be replayed to any point in time, and an
    edited row destroys the history that makes a study possible."""
    log = InMemoryActionLog()
    original = _event(1)
    log.append(original)
    log.append(_event(2, supersedes=original.event_id))

    assert len(log.events()) == 2, "a correction ADDS; it does not replace"
    assert log.events()[1].supersedes == original.event_id


def test_an_event_cannot_supersede_itself() -> None:
    with pytest.raises(ValueError, match="supersedes itself"):
        _event(1, supersedes=UUID(int=1))


def test_the_log_preserves_append_order() -> None:
    """Order is part of the contract: a log whose order is unspecified cannot be replayed, and
    replay is most of the reason to keep one."""
    log = InMemoryActionLog()
    for i in range(1, 6):
        log.append(_event(i))
    assert [event.event_id.int for event in log.events()] == [1, 2, 3, 4, 5]


def _event(n: int, *, supersedes: UUID | None = None) -> ActionEvent:
    return ActionEvent(
        event_id=UUID(int=n),
        recorded_at=datetime(2026, 8, 5, 9, n, tzinfo=UTC),
        action=_action(),
        supersedes=supersedes,
    )


# ---------------------------------------------------------------------------
# The proposer
# ---------------------------------------------------------------------------


def _position(sku: str, stock: Decimal | None) -> CurrentStateRow:
    return CurrentStateRow(
        tenant_id=TENANT,
        store_id=STORE,
        sku_id=sku,
        product_name=sku,
        product_category=None,
        sku_status="ACTIVE",
        current_retail_price=Decimal("89.0000"),
        unit_cost=None,
        promo_price=None,
        stock_qty=stock,
        reorder_point=None,
        currency="INR",
        expiry_date=None,
        last_source_event_at=None,
        last_updated_at=datetime(2026, 8, 4, tzinfo=UTC),
    )


def _finding(sku: str, *, dead: bool) -> DeadStockRow:
    return DeadStockRow(
        tenant_id=TENANT,
        store_id=STORE,
        sku_id=sku,
        days_since_last_sale=214 if dead else 3,
        is_dead_stock=dead,
    )


def _propose(findings: list[DeadStockRow], universe: list[CurrentStateRow]) -> list[Action]:
    return list(
        propose_dead_stock_actions(
            findings,
            universe,
            declaration=DEAD_STOCK,
            capability_versions=VERSIONS,
            as_of=AS_OF,
        )
    )


def test_only_dead_findings_produce_actions() -> None:
    """The evaluator emits one row per position so is_dead_stock carries information; deciding
    which findings deserve an action is an action-layer question."""
    actions = _propose(
        [_finding("DEAD", dead=True), _finding("ALIVE", dead=False)],
        [_position("DEAD", Decimal("40")), _position("ALIVE", Decimal("5"))],
    )
    assert [a.target["sku_id"] for a in actions] == ["DEAD"]


def test_every_proposed_action_carries_an_arm_and_full_provenance() -> None:
    (action,) = _propose([_finding("DEAD", dead=True)], [_position("DEAD", Decimal("40"))])
    assert action.arm in (Arm.TREATMENT, Arm.HOLDOUT)
    assert action.provenance.declaration_version == DEAD_STOCK.version
    assert action.provenance.capability_versions == VERSIONS
    assert action.provenance.as_of == AS_OF
    assert set(action.provenance.thresholds) == {"stale_after_days", "expires_after_days"}


def test_quantity_at_stake_is_unknown_when_stock_is_null() -> None:
    """None, not zero — see Action's docstring for why the difference is load-bearing."""
    (action,) = _propose([_finding("DEAD", dead=True)], [_position("DEAD", None)])
    assert action.quantity_at_stake is None


def test_a_position_missing_from_the_universe_gets_an_unknown_quantity() -> None:
    """Not a crash and not a zero. The finding is still real; only the quantity is unavailable."""
    (action,) = _propose([_finding("DEAD", dead=True)], [])
    assert action.quantity_at_stake is None


def test_the_expiry_comes_from_the_declared_threshold() -> None:
    (action,) = _propose([_finding("DEAD", dead=True)], [_position("DEAD", Decimal("40"))])
    expires_after = next(t for t in DEAD_STOCK.thresholds if t.name == "expires_after_days")
    assert action.expires_on == AS_OF + timedelta(days=expires_after.days)


def test_assignment_is_stable_across_proposer_runs() -> None:
    """The same SKU lands in the same arm every run. Without this the experiment is noise."""
    first = _propose([_finding("DEAD", dead=True)], [_position("DEAD", Decimal("40"))])
    second = _propose([_finding("DEAD", dead=True)], [_position("DEAD", Decimal("40"))])
    assert first[0].arm == second[0].arm


def test_both_arms_appear_across_a_realistic_population() -> None:
    """A guard against an inverted comparison putting everything in one arm — which would look
    like a working system producing no holdout."""
    findings = [_finding(f"SKU-{i}", dead=True) for i in range(200)]
    universe = [_position(f"SKU-{i}", Decimal("1")) for i in range(200)]
    assert {action.arm for action in _propose(findings, universe)} == {
        Arm.TREATMENT,
        Arm.HOLDOUT,
    }


def test_a_declaration_with_no_holdout_refuses_to_propose() -> None:
    """Rather than fabricating an arm. An action missing one looks analysable and is not."""
    from dataclasses import replace

    with pytest.raises(ValueError, match="declares no holdout"):
        propose_dead_stock_actions(
            [_finding("DEAD", dead=True)],
            [],
            declaration=replace(DEAD_STOCK, holdout=None),
            capability_versions=VERSIONS,
            as_of=AS_OF,
        )


def test_a_declaration_missing_a_threshold_refuses_to_propose() -> None:
    """Rather than fabricating an expiry."""
    from dataclasses import replace

    only_stale = tuple(t for t in DEAD_STOCK.thresholds if t.name == "stale_after_days")
    with pytest.raises(ValueError, match="expires_after_days"):
        propose_dead_stock_actions(
            [_finding("DEAD", dead=True)],
            [],
            declaration=replace(DEAD_STOCK, thresholds=only_stale),
            capability_versions=VERSIONS,
            as_of=AS_OF,
        )


def test_the_action_fixture_matches_what_the_proposer_produces() -> None:
    """The committed contract fixture is GENERATED from this code; a hand-written one can
    disagree with what it claims to describe."""
    import json
    import pathlib

    fixture = json.loads(
        (
            pathlib.Path(__file__).resolve().parents[3]
            / "contracts"
            / "synapse"
            / "fixtures"
            / "action"
            / "dead_stock_review.json"
        ).read_text(encoding="utf-8")
    )
    (action,) = _propose(
        [
            DeadStockRow(
                tenant_id=TENANT,
                store_id=STORE,
                sku_id="SKU-000123",
                days_since_last_sale=214,
                is_dead_stock=True,
            )
        ],
        [_position("SKU-000123", Decimal("40.000"))],
    )
    assert fixture["verb"] == action.verb.value
    assert fixture["arm"] == action.arm.value
    assert fixture["expires_on"] == action.expires_on.isoformat()
    assert fixture["provenance"]["thresholds"] == dict(action.provenance.thresholds)
    assert fixture["provenance"]["capability_versions"] == dict(action.provenance.capability_versions)
