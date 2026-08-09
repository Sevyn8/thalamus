"""E1 and E2: what Synapse can read, and what it computes. IN-PROCESS, not a query.

THE REASON THIS SERVICE IS PYTHON. Everything below comes from ``synapse.registry`` — object
state produced by import-time checks, not rows. ``registered_ids()``, ``declined_ids()``,
``declared_analysis_ids()``, and every ``Threshold``'s ``fitted`` flag and ``stands_in_for``
sentence. No TypeScript handler can reach them, and restating them in TS would be a second
source of truth for what Synapse can do — wrong on the first slice that adds a capability, and
wrong in the one place an operator goes to find out.

THIS SCREEN RENDERS THE REGISTRY AND NOTHING ELSE. The build spec listed seven capabilities,
taken from the architecture document; the registry holds FOUR — three registered and one
declined. ``basket_set``, ``identity_series`` and ``detections`` are named nowhere in it, so
rendering them would be presenting a wish as system state. That is the artifact class this
project has spent weeks removing, and it is what ``_DECLINED`` exists to prevent: an entry there
carries a VERIFIED reason, not an intention. ``basket_set`` is real work — 462 baskets have
arrived and nothing reads them — and it lives on the outstanding list until somebody writes down
why it cannot resolve today.

PLAIN NAME PLUS INTERNAL ID, both always. The plain name is what a person reads; the internal id
is what appears in logs, in ``synapse.run.analysis_id`` and in every action's provenance. A
screen showing only the friendly name makes a log line unsearchable from the UI that produced it.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from synapse.core.analysis import AnalysisDeclaration
from synapse.registry import (
    declaration_for,
    declared_analysis_ids,
    declined_ids,
    registered_ids,
)

__all__ = ["AnalysisView", "CapabilityView", "ThresholdView", "analyses", "capabilities"]


# Plain-language names, kept here rather than on the descriptors deliberately: a capability id is
# a contract between code and database, and a display string is a product decision that will be
# reworded by someone who is not editing Python. Every registered or declined id MUST appear —
# asserted below, so adding a capability without naming it fails a test rather than rendering a
# bare identifier to an operator.
_CAPABILITY_NAMES: Final[Mapping[str, str]] = {
    "current_state": "Current stock and prices",
    "daily_series": "Daily sales",
    "last_sale_at": "When each product last sold",
    "lead_time_distribution": "Supplier lead times",
}

_ANALYSIS_NAMES: Final[Mapping[str, str]] = {
    "dead_stock": "Stock that isn't selling",
    "stockout_risk": "Running out before the next delivery",
}


# WHAT EACH NUMBER MEANS, for the person reading the screen at 09:00.
#
# WHY THIS EXISTS AT ALL. The console used to render ``Threshold.stands_in_for`` under each
# number, and that field is not a description. Its name says what it is: the FITTED THING the
# constant substitutes for. ``analysis.py``'s ``__post_init__`` refuses to construct an unfitted
# threshold without one, so it is a gate on whoever writes a declaration, and it reads like one:
# the six values run from 232 to 1302 characters and name PERCENTILE_CONT, ``_DECLINED``,
# ``telemetry.connector_health``, ``missed_intervals`` and ``config.sources.schedule``. That is a
# reviewer's argument, correctly placed and genuinely valuable, rendered to an operator.
#
# stands_in_for IS UNCHANGED AND STILL SERVED. It is not the enemy; it was in the wrong audience.
#
# KEYED ON (analysis_id, name), NOT name. ``stale_after_days`` exists in BOTH analyses and means
# different things: 90 days of no sale before a product is dead, versus 3 days before sales data
# is too stale to divide into stock. ``expires_after_days`` collides the same way, 30 against 7.
# A name-only key would render the wrong sentence on four of the six rows.
#
# THE REGISTER IS "Flags products with stock on hand but no recent sales" -- one sentence, no
# internal identifiers, no reasoning about why the number is what it is. The "a convention" pill
# beside it already says the number is a choice rather than a measurement, which is the honest
# part an operator needs; this says what the choice DOES.
_THRESHOLD_DESCRIPTIONS: Final[Mapping[tuple[str, str], str]] = {
    ("dead_stock", "stale_after_days"): (
        "A product with stock but no sale for this long is treated as dead."
    ),
    ("dead_stock", "expires_after_days"): (
        "How long a dead-stock alert stays worth acting on before it is retired."
    ),
    ("stockout_risk", "window_days"): ("How far back sales are read to work out how fast a product sells."),
    ("stockout_risk", "at_risk_below_days"): ("Less cover than this at the current rate counts as at risk."),
    ("stockout_risk", "stale_after_days"): (
        "Sales data older than this is too stale to estimate a rate from."
    ),
    ("stockout_risk", "expires_after_days"): (
        "How long a stockout warning stays worth acting on before it is retired."
    ),
}


# WHY A CAPABILITY CANNOT BE READ, in one line.
#
# THE SAME DEFECT AS stands_in_for, FOUND WHILE FIXING IT. ``_DECLINED``'s reason is a verified
# audit note: it cites ``dis_validation.provenance``, classifies a column as a MAPPING-PRODUCED
# declared scalar, and records that a RECEIPT subtype was "verified by grep across services,
# libs, mappings and connectors". Every word earns its place in the registry and none of it
# belongs on a console. An operator needs to know THAT a capability cannot be read and roughly
# why; the grep trail is for whoever revisits the decision.
#
# declined_reason IS UNCHANGED AND STILL SERVED, same as stands_in_for.
_DECLINED_SUMMARIES: Final[Mapping[str, str]] = {
    "lead_time_distribution": (
        "Nothing records when an order was placed or when it arrived, so how long "
        "a delivery takes cannot be measured from what the platform holds."
    ),
}


@dataclass(frozen=True)
class CapabilityView:
    """One row of E1.

    ``declined_reason`` is the whole difference between "nobody has written this yet" and "this
    cannot be written". The first is a work item; the second is a verified fact about the data,
    and it is the reason ``lead_time_distribution`` will never resolve however much code anyone
    writes. The UI must not flatten them into one grey tag.
    """

    capability_id: str
    name: str
    resolves: bool
    # THE AUDIT NOTE. Still served, deliberately, and no longer rendered: no test in this
    # service forbids serving a field the console does not draw, and dropping it would remove
    # the only machine-readable record of WHY from the API. See _DECLINED_SUMMARIES.
    declined_reason: str | None
    # The one-line operator-facing version of the same fact. None when the capability resolves.
    declined_summary: str | None
    used_by: tuple[str, ...]


@dataclass(frozen=True)
class ThresholdView:
    """One number an analysis uses, and whether it was measured.

    ``stands_in_for`` IS RENDERED VERBATIM AND NEVER SUMMARISED. Each one names precisely what
    the number substitutes for and why that thing cannot be known — one of them cites a declined
    capability, another cites a telemetry column that is NULL in Phase A. Summarising turns a
    checkable statement into a shrug, and the honesty is the only thing making these constants
    defensible.
    """

    name: str
    days: int
    fitted: bool
    # THE REVIEWER'S ARGUMENT. Still served, deliberately, and no longer rendered. See
    # _THRESHOLD_DESCRIPTIONS for what replaced it on screen and why.
    stands_in_for: str | None
    # What the number DOES, for an operator. Always present: the coverage test refuses a
    # threshold that has no entry in _THRESHOLD_DESCRIPTIONS, so this is never a bare name.
    description: str


@dataclass(frozen=True)
class AnalysisView:
    """One row of E2, with its ceiling and its numbers."""

    analysis_id: str
    name: str
    version: str
    requires: tuple[str, ...]
    max_rung: str
    thresholds: tuple[ThresholdView, ...]
    holdout_percent: int | None


def _used_by(capability_id: str) -> tuple[str, ...]:
    """Which analyses require this capability. Derived, never a maintained list."""
    return tuple(
        analysis_id
        for analysis_id in declared_analysis_ids()
        for declaration in (declaration_for(analysis_id),)
        if declaration is not None and any(r.capability_id == capability_id for r in declaration.requires)
    )


def capabilities() -> tuple[CapabilityView, ...]:
    """Every capability the registry knows: resolving first, then declined.

    Both lists come from the registry, so this cannot show one that does not exist and cannot
    omit one that does.
    """
    from synapse.registry import _DECLINED  # the reasons, keyed by id

    rows = [
        CapabilityView(
            capability_id=capability_id,
            name=_CAPABILITY_NAMES.get(capability_id, capability_id),
            resolves=True,
            declined_reason=None,
            declined_summary=None,
            used_by=_used_by(capability_id),
        )
        for capability_id in registered_ids()
    ]
    rows.extend(
        CapabilityView(
            capability_id=capability_id,
            name=_CAPABILITY_NAMES.get(capability_id, capability_id),
            resolves=False,
            declined_reason=_DECLINED[capability_id],
            declined_summary=_DECLINED_SUMMARIES.get(capability_id),
            used_by=_used_by(capability_id),
        )
        for capability_id in declined_ids()
    )
    return tuple(rows)


def _view(declaration: AnalysisDeclaration) -> AnalysisView:
    return AnalysisView(
        analysis_id=declaration.id,
        name=_ANALYSIS_NAMES.get(declaration.id, declaration.id),
        version=declaration.version,
        requires=tuple(r.capability_id for r in declaration.requires),
        max_rung=declaration.max_rung.value,
        thresholds=tuple(
            ThresholdView(
                name=t.name,
                days=t.days,
                fitted=t.fitted,
                stands_in_for=t.stands_in_for,
                # FALLS BACK TO THE BARE NAME, and the coverage test is what stops that ever
                # being what an operator sees. A KeyError here would take the whole catalogue
                # down for one missing sentence; a test that fails the build is the right place
                # to refuse, not the request path.
                description=_THRESHOLD_DESCRIPTIONS.get((declaration.id, t.name), t.name),
            )
            for t in declaration.thresholds
        ),
        holdout_percent=declaration.holdout.holdout_percent if declaration.holdout else None,
    )


def analyses() -> tuple[AnalysisView, ...]:
    """Every declared analysis. This screen never offers an edit: declarations are git."""
    return tuple(
        _view(declaration)
        for analysis_id in declared_analysis_ids()
        for declaration in (declaration_for(analysis_id),)
        if declaration is not None
    )
