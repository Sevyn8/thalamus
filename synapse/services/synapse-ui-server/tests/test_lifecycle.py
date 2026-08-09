"""Alert lifecycle: the closed vocabularies, the target grain, and the read-time derivation.

THE SEMANTIC THIS FILE EXISTS FOR is per-target resolution. An operator who snoozes an alert
means "stop showing me this product at this store for 30 days". Tomorrow's detection of the same
thing is a NEW row with a NEW event_id, so a per-event match would evaporate on exactly the alert
the snooze was meant to silence. ``test_a_new_detection_on_a_snoozed_target_is_still_snoozed`` is
the one that would fail if anybody re-keyed it.

WHAT IS ASSERTED ELSEWHERE, deliberately not restated here: that the write surface is one
statement in one module under one credential (test_no_write_path.py, mutation-proven), and that
the table refuses UPDATE/DELETE and bad vocabulary values against a real Postgres
(tests/integration/test_migration_0006_live.py — the 0005 lesson: no migration ships unexecuted).
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from uuid import UUID

import pytest
from synapse_ui_server import reads
from synapse_ui_server.lifecycle import (
    Decision,
    DismissReason,
    LifecycleVerb,
    LifecycleWriteError,
)

TENANT = UUID("019fb16b-e402-7dce-b026-6fa9f4919242")
EVENT = UUID("019fb16b-0000-7000-8000-00000000ab01")
TARGET = {"tenant_id": str(TENANT), "store_id": "s", "sku_id": "SKU-1"}


def _decision(**overrides: object) -> Decision:
    base: dict[str, object] = {
        "action_event_id": EVENT,
        "tenant_id": TENANT,
        "declaration_id": "dead_stock",
        "target": TARGET,
        "verb": LifecycleVerb.ACKNOWLEDGE,
        "reason": None,
        "snoozed_until": None,
        "actor_subject": "auth0|abc",
    }
    base.update(overrides)
    return Decision(**base)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# The closed vocabularies
# ---------------------------------------------------------------------------


def test_the_verb_set_is_exactly_three() -> None:
    """Mirrors ck_action_events_verb. A fourth verb is a migration, not a constant."""
    assert {v.value for v in LifecycleVerb} == {"snooze", "dismiss", "acknowledge"}


def test_the_reason_set_is_exactly_the_four_training_labels() -> None:
    """These are false-positive training labels, not UI copy: something has to GROUP BY them in
    a year. A fifth is a migration."""
    assert {r.value for r in DismissReason} == {
        "seasonal",
        "display_stock",
        "discontinued",
        "wrong_data",
    }


def test_a_dismissal_without_a_reason_is_refused() -> None:
    """An unlabelled dismissal is an unlabelled negative example, which is the entire reason for
    asking. Refused at construction, before any connection is opened."""
    with pytest.raises(LifecycleWriteError, match="must carry a reason"):
        _decision(verb=LifecycleVerb.DISMISS)


def test_a_reason_on_a_non_dismissal_is_refused() -> None:
    """The other direction, so a training label cannot arrive attached to an acknowledgement and
    pollute the counts."""
    with pytest.raises(LifecycleWriteError, match="takes no reason"):
        _decision(verb=LifecycleVerb.ACKNOWLEDGE, reason=DismissReason.SEASONAL)


def test_a_snooze_without_an_expiry_is_refused() -> None:
    """A snooze with no expiry is a dismissal wearing the wrong verb, and it would never
    resurface — which is the failure an operator would not notice."""
    with pytest.raises(LifecycleWriteError, match="must carry an expiry"):
        _decision(verb=LifecycleVerb.SNOOZE)


def test_an_expiry_on_a_non_snooze_is_refused() -> None:
    with pytest.raises(LifecycleWriteError, match="takes no expiry"):
        _decision(verb=LifecycleVerb.DISMISS, reason=DismissReason.SEASONAL, snoozed_until=date(2026, 9, 1))


def test_the_valid_combinations_construct() -> None:
    """THE BASELINE. Without it every refusal above would also pass against a Decision that
    rejected everything."""
    assert _decision(verb=LifecycleVerb.ACKNOWLEDGE).reason is None
    assert _decision(verb=LifecycleVerb.SNOOZE, snoozed_until=date(2026, 9, 1)).snoozed_until
    assert _decision(verb=LifecycleVerb.DISMISS, reason=DismissReason.WRONG_DATA).reason


# ---------------------------------------------------------------------------
# The target grain — the hard semantic
# ---------------------------------------------------------------------------


def test_the_derivation_matches_on_the_target_not_the_event() -> None:
    """THE ONE THAT ENCODES THE DECISION. If the LATERAL ever joins on action_event_id, a snooze
    stops covering tomorrow's detection of the same product — which is what the operator asked
    for — and every other test here would still pass.
    """
    sql = str(reads._ALERT_DETAIL)
    assert "e.declaration_id = a.declaration_id" in sql
    assert "e.target = a.target" in sql
    assert "e.action_event_id" not in sql, (
        "the lifecycle join matched on the clicked event; a snooze would then evaporate on the "
        "next detection of the same target, which is exactly what it was meant to silence"
    )


def test_a_new_detection_on_a_snoozed_target_is_still_snoozed() -> None:
    """THE SNOOZED-NEW-DETECTION CASE, asserted on the join's shape because it is a SQL property.

    Tomorrow's alert for the same (declaration_id, target) is a different row with a different
    event_id and a later as_of. The LATERAL keys on the grain and not on the row, so it resolves
    to the same lifecycle event — the snooze covers the target, which is what "snooze this
    product at this store" means.
    """
    sql = str(reads._TENANT_ALERTS)
    assert "LEFT JOIN LATERAL" in sql
    # Nothing in the correlation mentions the alert's identity or its date, so a new row for the
    # same target cannot fall outside it.
    correlation = sql.split("LEFT JOIN LATERAL")[1].split("ON TRUE")[0]
    for row_specific in ("a.event_id", "a.as_of", "a.recorded_at"):
        assert row_specific not in correlation, (
            f"the lifecycle correlation references {row_specific}, so it is per-row rather than "
            "per-target and a snooze would not survive the next detection"
        )


def test_the_latest_decision_wins_and_ties_break_deterministically() -> None:
    """A dismissal after a snooze must win, and a re-snooze after a lapsed one must too. Ties on
    recorded_at break on the id so two reads of the same data cannot disagree."""
    sql = str(reads._ALERT_DETAIL)
    assert "DISTINCT ON (e.tenant_id, e.declaration_id, e.target)" in sql
    assert "e.recorded_at DESC, e.lifecycle_event_id DESC" in sql


def test_the_derivation_is_a_read_and_suppresses_no_detection() -> None:
    """D1. Lifecycle is a LEFT JOIN on the console's read path; nothing filters synapse.actions
    out of existence and the orchestrator never reads this table. A snoozed target keeps
    accumulating rows, which is what makes the post-expiry history complete."""
    assert "LEFT JOIN LATERAL" in str(reads._ALERT_DETAIL)
    import pathlib

    orchestrator = pathlib.Path(reads.__file__).resolve().parents[5] / "src" / "synapse"
    hits = [p.name for p in orchestrator.rglob("*.py") if "action_events" in p.read_text(encoding="utf-8")]
    assert hits == [], f"the analysis plane reads or writes the lifecycle table: {hits}"


def test_every_alert_query_carries_the_lifecycle_state() -> None:
    """Both surfaces render it, so both must select it; a list showing 'open' for a dismissed
    alert is worse than one showing no state at all."""
    for statement in (reads._ALERT_DETAIL, reads._TENANT_ALERTS):
        sql = str(statement)
        for column in (
            "lifecycle_verb",
            "lifecycle_reason",
            "lifecycle_snoozed_until",
            # B2a. The DERIVED state, not just the raw columns. The console no longer computes
            # one, so a statement that omits this serves a row nothing can render a chip from.
            "lifecycle_state",
        ):
            assert column in sql, f"{column} missing"


def test_an_untouched_alert_carries_no_lifecycle_state() -> None:
    """None across the board IS the open state. A LEFT JOIN is what makes 'nobody has acted' the
    default rather than a row that has to exist."""
    row = reads.AlertRow(
        event_id=EVENT,
        as_of=date(2026, 8, 6),
        recorded_at=datetime(2026, 8, 6, tzinfo=UTC),
        declaration_id="dead_stock",
        declaration_version="0.1.0",
        verb="review",
        arm="treatment",
        expires_on=date(2026, 9, 5),
        quantity_at_stake=None,
        days_since_last_sale=214,
        days_of_cover=None,
        thresholds={},
        target=TARGET,
        store_id=None,
        sku_id="SKU-1",
        store_name=None,
        product_name=None,
        current_stock_qty=None,
        lifecycle_verb=None,
        lifecycle_reason=None,
        lifecycle_snoozed_until=None,
        lifecycle_recorded_at=None,
        lifecycle_actor=None,
        lifecycle_state="open",
    )
    assert row.lifecycle_verb is None
