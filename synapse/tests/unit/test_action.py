"""Actions, provenance, the append-only log, and the dead_stock proposer. All pure.

THE LOAD-BEARING TESTS ARE THE TWO ABOUT WHAT CANNOT BE RETROFITTED:

- an action cannot be built without an arm, and there is no value meaning "not assigned";
- an action cannot be built without complete provenance.

Both are constructor-level rather than review-level, because both are unfixable after the fact.
An action recorded today without an arm is permanently outside any study, and no migration
recovers it.

The append-only log's own properties moved to test_action_log.py when the protocol split into
an appender and a reader — they are parameterised over every implementation now, so they no
longer belong to a file about the action TYPES.
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from uuid import UUID

import pytest

from synapse.core.action import Action, Provenance, Verb
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


# ---------------------------------------------------------------------------
# Actionability (slice 10). A FLAG, never a filter.
# ---------------------------------------------------------------------------


def test_a_zero_quantity_action_is_not_actionable() -> None:
    """SKU-0029'S SHAPE, and the reason this slice exists.

    The only real action in the log is a never-sold SKU with ZERO stock: genuine catalogue
    hygiene, and nothing to mark down, transfer or clear. If delivery existed today that is the
    first thing a client would ever see from Synapse, which is why actionability had to exist
    before any rung is promoted.
    """
    assert _action(quantity_at_stake=Decimal("0.000")).is_actionable is False


def test_a_positive_quantity_action_is_actionable() -> None:
    """THE BASELINE. Without it every assertion here would also pass against a property that
    returned False unconditionally — the refusal-test failure this project has already paid for."""
    assert _action(quantity_at_stake=Decimal("40.000")).is_actionable is True


def test_the_smallest_positive_quantity_is_actionable() -> None:
    """The boundary is > 0, not >= some floor. A single unit is a real unit; inventing a minimum
    would be the first threshold in this plane that nobody could defend."""
    assert _action(quantity_at_stake=Decimal("0.001")).is_actionable is True


def test_an_unknown_quantity_is_not_actionable() -> None:
    """None means UNKNOWN, never zero (see Action's docstring). stock_qty is nullable in canonical
    and dead_stock never inspects it, so a dead position with no stock figure reaches here as
    None. Nothing can be decided from it, so it is not actionable — for a DIFFERENT reason than
    the zero above."""
    assert _action(quantity_at_stake=None).is_actionable is False


def test_unknown_and_zero_stay_distinguishable_in_the_data() -> None:
    """THE BOOL IS A VIEW, NOT A LOSSY ENCODING, and this is what makes that claim checkable.

    Both cases answer False, and a reader who needs to know WHICH reads quantity_at_stake — which
    is stored on the row. If this ever stops holding, the bool has started destroying information
    and the tri-state argument reopens.
    """
    unknown = _action(quantity_at_stake=None)
    verified_zero = _action(quantity_at_stake=Decimal("0.000"))
    assert unknown.is_actionable == verified_zero.is_actionable is False
    assert unknown.quantity_at_stake is None
    assert verified_zero.quantity_at_stake == Decimal("0")


def test_actionability_is_not_a_filter_on_the_proposers() -> None:
    """D1 IS STRUCTURAL AND THIS PINS IT. A low-value action is still a recorded action: the
    denominator attribution needs is destroyed by any filter applied before recording.

    Asserted by counting the proposer's output over a universe containing a zero-stock dead
    position — the one this slice flags as not actionable. If a future edit ever routes
    is_actionable into the proposer, this count drops and the test fails.
    """
    findings = [
        DeadStockRow(TENANT, STORE, "SKU-0029", days_since_last_sale=None, is_dead_stock=True),
        DeadStockRow(TENANT, STORE, "SKU-2", days_since_last_sale=200, is_dead_stock=True),
    ]
    universe = [
        _position("SKU-0029", Decimal("0.000")),
        _position("SKU-2", Decimal("40.000")),
    ]
    actions = propose_dead_stock_actions(
        findings, universe, declaration=DEAD_STOCK, capability_versions=VERSIONS, as_of=AS_OF
    )
    assert len(actions) == 2, "the proposer emitted fewer actions than dead findings"
    assert [a.is_actionable for a in actions] == [False, True]


# ---------------------------------------------------------------------------
# The observation columns (slice 10). Not scores.
# ---------------------------------------------------------------------------


def test_the_observation_fields_default_to_none() -> None:
    """DEFAULTED, so all ten modules that construct an Action keep working unchanged. A required
    field here would have been a breaking change to a frozen contract for a value nothing reads
    yet."""
    action = _action()
    assert action.days_since_last_sale is None
    assert action.days_of_cover is None


def test_a_negative_last_sale_age_is_refused() -> None:
    """THE CLOCK-SKEW BOUNDARY. dead_stock deliberately passes a negative age through rather than
    clamping it — a POS can date a sale after as_of and clamping would hide the skew. It is
    refused HERE because a STORED negative age reads as extremely fresh to anything ranking on it
    later. Visible in the finding, never in the log."""
    with pytest.raises(ValueError, match="clock skew"):
        _action(days_since_last_sale=-1)


def test_a_negative_cover_is_refused() -> None:
    with pytest.raises(ValueError, match="days_of_cover"):
        _action(days_of_cover=Decimal("-0.001"))


def test_zero_is_a_legal_observation() -> None:
    """Zero days of cover is a real reading — stock on hand with demand that exhausts it today —
    and zero days since the last sale means it sold today. Neither is negative and neither is
    missing, so both must construct."""
    assert _action(days_since_last_sale=0).days_since_last_sale == 0
    assert _action(days_of_cover=Decimal("0")).days_of_cover == Decimal("0")
