"""ONE LIFECYCLE AUTHORITY, and the counts that have to agree with it (B2a).

WHAT THIS FILE EXISTS TO STOP HAPPENING AGAIN. Before B2a there were THREE derivations of
"open" and they disagreed three separate ways:

  1. ``_LIFECYCLE_STATE``, the CASE the fleet inbox and its chips use. Correct.
  2. An INLINE COPY of the lifecycle lateral with its own WHERE inside ``_FLEET``, which
     counted acknowledged as open, read ``synapse.actions`` rather than the analytical view,
     and anchored the snooze comparison on ``CURRENT_DATE``.
  3. ``alertState()`` in the console's TypeScript, whose ``isOpen()`` also counted
     acknowledged.

The symptom on staging was an inbox reading "Open 6, Acknowledged 5" beside a fleet page and a
tenant page both reading 11. Only ONE of the three divergences produced that number; the other
two were waiting for the first snoozed alert and the first quarantined-tenant row.

THE TESTS BELOW ARE TEXT-LEVEL AND THEREFORE WEAK ON THEIR OWN. They prove the constructs are
single-sourced and that no copy has crept back. They CANNOT prove the SQL is correct, because
they never execute it: this file guards the SHAPE, not the ANSWER.

HOW THE ANSWER WAS PROVEN, since claiming otherwise would be the exact defect this slice is
about. During B2a every rebuilt statement was executed against a disposable Postgres loaded
from ``synapse/schemas/postgres/*.sql``, seeded with six targets for one tenant (two untouched,
one acknowledged, one dismissed, one active snooze, one lapsed snooze) plus one untouched row
for a quarantined tenant. Observed: chips ``{open: 3, snoozed: 1, acknowledged: 1,
dismissed: 1}``, fleet ``open_alerts`` 3, ``TenantDetail.open_alerts`` 3, quarantined tenant 0,
and the chips summing to the six unfiltered rows. The numbers are in the commit message.

THAT RUN IS NOT REPRODUCED BY ``make test`` AND NOTHING HERE PRETENDS IT IS. Re-proving it
needs the integration DSN (see ``tests/integration/conftest.py``), or the same throwaway
harness rebuilt. A file asserting it runs in CI when nothing runs it is a documented failure
mode in this repository, and this docstring is deliberately not one.
"""

from __future__ import annotations

import re

from synapse_ui_server import reads


def _norm(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


# ---------------------------------------------------------------------------
# ONE CONSTRUCT, NOT THREE
# ---------------------------------------------------------------------------


def test_the_state_case_is_defined_once_and_shared() -> None:
    """The distinctive text of _LIFECYCLE_STATE must appear in every statement with an opinion
    about whether an alert is open. Two copies would drift, and the drift is invisible until a
    count on one screen disagrees with a list on another."""
    marker = "WHEN le.verb = 'acknowledge'"
    for name in (
        "_FLEET",
        "_TENANT",
        "_TENANT_ALERTS",
        "_ALERT_DETAIL",
        "_FLEET_ALERTS",
        "_FLEET_ALERT_STATE_COUNTS",
    ):
        assert marker in _norm(str(getattr(reads, name))), f"{name} does not use the shared _LIFECYCLE_STATE"


def test_the_fleet_no_longer_carries_its_own_lifecycle_lateral() -> None:
    """THE DELETED COPY, asserted gone by its own fingerprints rather than by counting lines.

    The inline version selected `e.verb, e.snoozed_until` (a narrower list than the shared
    join's) and grouped on `act.tenant_id`. Neither string can occur if the shared construct is
    the only lateral left.
    """
    fleet = _norm(str(reads._FLEET))
    assert "act.tenant_id" not in fleet, "the inline open-alerts lateral is still present"
    assert "e.verb, e.snoozed_until" not in fleet, "the inline lateral's projection survives"


def test_no_statement_anchors_a_snooze_on_current_date() -> None:
    """CURRENT_DATE resolves in the DB session's timezone, which is configuration rather than
    contract. The console mints a snooze expiry in UTC, so the comparison is anchored in UTC
    explicitly. The deleted _FLEET copy used CURRENT_DATE and is why this test exists."""
    for name in ("_FLEET", "_TENANT", "_FLEET_ALERTS", "_FLEET_ALERT_STATE_COUNTS"):
        assert "CURRENT_DATE" not in str(getattr(reads, name)), (
            f"{name} anchors a date on the session timezone"
        )


def test_the_open_count_reads_the_analytical_view() -> None:
    """The quarantined fixture tenant's thirteen immortal rows are excluded from analytical
    surfaces by migration 0007, and a count an operator reads is exactly that. The inbox already
    read the view; the roster did not, which is the second of the three divergences."""
    assert "synapse.actions_analytical" in reads._OPEN_ALERTS_BY_TENANT


def test_the_fleet_and_the_tenant_header_share_the_open_count_construct() -> None:
    """Same subquery text in both, so the roster and the tenant stat strip cannot disagree
    about a number they both label "open alerts"."""
    shared = _norm(reads._OPEN_ALERTS_BY_TENANT)
    assert shared in _norm(str(reads._FLEET))
    assert shared in _norm(str(reads._TENANT))


def test_actions_recorded_still_counts_the_unfiltered_table() -> None:
    """THE DENOMINATOR IS NOT REDEFINED. open_alerts moved to the analytical view;
    actions_recorded stays on synapse.actions because it is the attribution denominator D1
    protects, and changing what it counts under the same label would silently change what an
    older screenshot meant."""
    for name in ("_FLEET", "_TENANT"):
        sql = _norm(str(getattr(reads, name)))
        assert "count(*) AS actions_recorded" in sql or "count(*) AS actions" in sql
        assert "FROM synapse.actions GROUP BY tenant_id" in sql, (
            f"{name} no longer counts actions_recorded over the unfiltered table"
        )


def test_the_alert_row_carries_the_served_state() -> None:
    """The console renders a state rather than deriving one, so every alert-bearing row type
    has to carry it. Without this the TypeScript deletion would have left surfaces with nothing
    to render."""
    assert "lifecycle_state" in reads.AlertRow.__dataclass_fields__
    assert "lifecycle_state" in reads.FleetAlertRow.__dataclass_fields__


def test_the_tenant_detail_carries_a_server_side_open_count() -> None:
    """The tenant page counted open rows out of its own LIMIT-50 list, which counts what is
    DISPLAYED while the stat strip asserts a fact about the TENANT. Above the limit the strip
    was silently wrong."""
    assert "open_alerts" in reads.TenantDetail.__dataclass_fields__


def test_the_state_vocabulary_is_exported_once() -> None:
    """ALERT_STATES is what lets a route return zeros rather than omitting a state: a missing
    key and a zero look identical to a chip and only one is true. Defined once, beside the CASE
    that produces the values."""
    assert reads.ALERT_STATES == ("open", "snoozed", "acknowledged", "dismissed")
