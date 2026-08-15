"""E1 and E2 render the REGISTRY, and only the registry.

THE FAILURE THIS FILE EXISTS TO PREVENT. The build spec listed seven capabilities, taken from an
architecture document, in a page whose stated premise was that every figure came from staging.
Three of them are in no registry map at all. Shipping that screen would have presented a wish as
system state — the artifact class this project has spent weeks deleting — and it would have been
invisible, because a table of seven plausible rows looks exactly like a table of seven real ones.

So these tests assert AGAINST THE REGISTRY rather than against a list restated here. A test
carrying its own copy of the expected capabilities would have passed happily against the
seven-row version.
"""

from __future__ import annotations

from synapse_ui_server import catalog

from synapse.registry import declared_analysis_ids, declined_ids, registered_ids


def test_every_capability_shown_is_one_the_registry_knows() -> None:
    """No invented rows. The set rendered must be exactly registered + declined."""
    shown = {row.capability_id for row in catalog.capabilities()}
    assert shown == set(registered_ids()) | set(declined_ids())


def test_no_capability_the_registry_knows_is_omitted() -> None:
    """The other direction, and it is not the same test. A screen that silently dropped a
    declined capability would hide the one row an operator most needs — the thing that cannot be
    fixed by writing code."""
    shown = {row.capability_id for row in catalog.capabilities()}
    for capability_id in (*registered_ids(), *declined_ids()):
        assert capability_id in shown, f"{capability_id} is registered but not rendered"


def test_the_invented_capabilities_are_absent() -> None:
    """Named explicitly, because this is the specific regression.

    ``basket_set`` is REAL WORK — 462 baskets have arrived and nothing reads them — but it is
    not a declined capability, and putting it in ``_DECLINED`` needs a verified reason of its
    own. Until then it belongs on the outstanding list, not on a screen describing system state.
    """
    shown = {row.capability_id for row in catalog.capabilities()}
    # VACUITY GUARD. `not shown & {...}` is true of an empty set, so an empty catalogue would
    # report that the invented capabilities are absent while nothing at all was rendered.
    assert shown, "the catalogue rendered nothing; an empty set satisfies the assertion below"
    assert not shown & {"basket_set", "identity_series", "detections"}


def test_a_declined_capability_carries_its_verified_reason() -> None:
    """``resolves=False`` alone would flatten "nobody wrote it" into "it cannot be written".
    The reason is what distinguishes a work item from a fact about the data."""
    declined = [row for row in catalog.capabilities() if not row.resolves]
    assert declined, "lead_time_distribution is declined; the fixture must not be empty"
    for row in declined:
        assert row.declined_reason, f"{row.capability_id} is declined with no reason"
        assert len(row.declined_reason) > 80, "a one-word reason is not a verified reason"


def test_a_resolving_capability_carries_no_declined_reason() -> None:
    seen = 0
    for row in catalog.capabilities():
        if row.resolves:
            seen += 1
            assert row.declined_reason is None
    assert seen >= 1, "no resolving capability was seen; this test proved nothing"


def test_used_by_is_derived_from_the_declarations() -> None:
    """Not a maintained list. current_state is required by both analyses; last_sale_at by
    dead_stock alone. If this were hand-kept it would be wrong one slice after it was written."""
    by_id = {row.capability_id: row for row in catalog.capabilities()}
    assert set(by_id["current_state"].used_by) == {"dead_stock", "stockout_risk"}
    assert set(by_id["last_sale_at"].used_by) == {"dead_stock"}
    assert set(by_id["daily_series"].used_by) == {"stockout_risk"}
    assert by_id["lead_time_distribution"].used_by == ()


def test_every_rendered_capability_has_a_plain_language_name() -> None:
    """D4: plain name AND internal id. A capability added without naming it would otherwise
    render its bare identifier to an operator, which is the failure the decision was about."""
    seen = 0
    for row in catalog.capabilities():
        seen += 1
        assert row.name != row.capability_id, (
            f"{row.capability_id} has no plain-language name; add one to _CAPABILITY_NAMES"
        )
    assert seen >= 1, "no capability was rendered; a loop over nothing asserts nothing"


# ---------------------------------------------------------------------------
# E2
# ---------------------------------------------------------------------------


def test_every_declared_analysis_is_shown() -> None:
    assert {row.analysis_id for row in catalog.analyses()} == set(declared_analysis_ids())


def test_every_analysis_has_a_plain_language_name() -> None:
    seen = 0
    for row in catalog.analyses():
        seen += 1
        assert row.name != row.analysis_id, f"{row.analysis_id} needs a name in _ANALYSIS_NAMES"
    assert seen >= 1, "no analysis was rendered; a loop over nothing asserts nothing"


def test_the_ceiling_is_shown_and_is_shadow_today() -> None:
    """The ceiling is the envelope — what the analysis is PERMITTED to do, ever. Showing it is
    how an operator sees that nothing can currently reach a client, without reading code."""
    assert {row.max_rung for row in catalog.analyses()} == {"shadow"}


def test_an_unfitted_threshold_carries_its_stands_in_for_verbatim() -> None:
    """RENDERED VERBATIM, NEVER SUMMARISED. Each sentence names what the number substitutes for
    and why that cannot be known — one cites a declined capability, another a telemetry column
    that is NULL in Phase A. Summarising turns a checkable statement into a shrug, and the
    honesty is the only thing that makes these constants defensible."""
    seen = 0
    for analysis in catalog.analyses():
        for threshold in analysis.thresholds:
            if not threshold.fitted:
                seen += 1
                assert threshold.stands_in_for, (
                    f"{analysis.analysis_id}.{threshold.name} is unfitted with no stands_in_for; "
                    "the Threshold constructor should have refused to build it"
                )
                assert len(threshold.stands_in_for) > 100, "truncated stands_in_for"
    assert seen >= 6, f"expected every threshold in both analyses to be unfitted, saw {seen}"


def test_thresholds_are_not_summarised_or_reformatted() -> None:
    """The view must carry the declaration's text unchanged — asserted by identity against the
    declaration rather than by a copy of the expected string, which would drift."""
    from synapse.registry import declaration_for

    for analysis in catalog.analyses():
        declaration = declaration_for(analysis.analysis_id)
        assert declaration is not None
        declared = {t.name: t.stands_in_for for t in declaration.thresholds}
        for threshold in analysis.thresholds:
            assert threshold.stands_in_for == declared[threshold.name]


# ===========================================================================================
# OPERATOR-FACING COPY, AND THE AUDIENCE MISTAKE IT EXISTS TO STOP REPEATING
# ===========================================================================================
#
# The console rendered ``Threshold.stands_in_for`` under every threshold and ``_DECLINED``'s
# reason under every declined capability. Both are correctly written and correctly placed; both
# are aimed at whoever REVIEWS a declaration. One names PERCENTILE_CONT and reasons about
# capability slices, the other cites dis_validation.provenance and records a grep audit. Neither
# is copy for somebody reading a screen at 09:00.
#
# The fields stay exactly as declared and are still served. What changed is which of them the UI
# draws, and the tests below are what stop a NEW threshold or a NEW declined capability arriving
# with no operator-facing line, because a new one arrives in a Python deploy and nothing else
# would notice.


def test_every_threshold_has_an_operator_description() -> None:
    """THE COVERAGE GATE. Modelled on test_every_rendered_capability_has_a_plain_language_name,
    with the vacuity guard those two do not have: iterating an empty catalogue would pass while
    checking nothing, which is the failure this repository keeps writing tests about.

    Falls back to the bare threshold name in catalog._view, so an undescribed threshold renders
    its identifier rather than crashing the request. This is where that gets refused.
    """
    seen = 0
    for analysis in catalog.analyses():
        for threshold in analysis.thresholds:
            seen += 1
            assert threshold.description != threshold.name, (
                f"{analysis.analysis_id}.{threshold.name} has no operator description; "
                "add one to _THRESHOLD_DESCRIPTIONS keyed on (analysis_id, name)"
            )
    assert seen >= 6, f"expected at least the six declared thresholds, saw {seen}"


def test_threshold_descriptions_are_keyed_per_analysis() -> None:
    """THE COLLISION THAT MAKES A NAME-ONLY KEY WRONG. ``stale_after_days`` is 90 days of no sale
    in dead_stock and 3 days of stale data in stockout_risk; ``expires_after_days`` is 30 against
    7. Four of the six rows share a name with a different meaning, so a flat map would render the
    wrong sentence on each. Asserted here rather than trusted to the reader of the map.
    """
    by_name: dict[str, set[str]] = {}
    for analysis in catalog.analyses():
        for threshold in analysis.thresholds:
            by_name.setdefault(threshold.name, set()).add(threshold.description)
    shared = {name: texts for name, texts in by_name.items() if len(texts) > 1}
    assert "stale_after_days" in shared, (
        "stale_after_days no longer differs between analyses; the compound key may have "
        "silently stopped mattering, or a description has been copied across two meanings"
    )
    for name, texts in shared.items():
        assert len(texts) > 1, f"{name} renders one sentence for two different meanings"


def test_every_declined_capability_has_an_operator_summary() -> None:
    """The same gate for _DECLINED. A capability declared unresolvable without a plain sentence
    would leave the page saying only that something is unavailable, with the audit note as the
    sole explanation available to render.
    """
    seen = 0
    for row in catalog.capabilities():
        if row.resolves:
            assert row.declined_summary is None, (
                f"{row.capability_id} resolves but carries a declined summary"
            )
            continue
        seen += 1
        assert row.declined_summary, (
            f"{row.capability_id} is declined with no operator summary; add one to _DECLINED_SUMMARIES"
        )
    assert seen >= 1, "no declined capability was seen; this test proved nothing"


def test_the_reviewer_fields_are_still_served_unchanged() -> None:
    """UNRENDERED IS NOT UNSERVED. Nothing in this service forbids serving a field the console
    does not draw, and these two are the only machine-readable record of WHY a number or a
    refusal is what it is. Dropping them from the view would move that record out of the API and
    into a git history nobody queries. Asserted by identity against the declaration so a future
    edit cannot quietly summarise them into the thing they were rescued from being.
    """
    from synapse.registry import _DECLINED, declaration_for

    for analysis in catalog.analyses():
        declaration = declaration_for(analysis.analysis_id)
        assert declaration is not None
        declared = {t.name: t.stands_in_for for t in declaration.thresholds}
        for threshold in analysis.thresholds:
            assert threshold.stands_in_for == declared[threshold.name]

    for row in catalog.capabilities():
        if not row.resolves:
            assert row.declined_reason == _DECLINED[row.capability_id]
