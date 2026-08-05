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
    for row in catalog.capabilities():
        if row.resolves:
            assert row.declined_reason is None


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
    for row in catalog.capabilities():
        assert row.name != row.capability_id, (
            f"{row.capability_id} has no plain-language name; add one to _CAPABILITY_NAMES"
        )


# ---------------------------------------------------------------------------
# E2
# ---------------------------------------------------------------------------


def test_every_declared_analysis_is_shown() -> None:
    assert {row.analysis_id for row in catalog.analyses()} == set(declared_analysis_ids())


def test_every_analysis_has_a_plain_language_name() -> None:
    for row in catalog.analyses():
        assert row.name != row.analysis_id, f"{row.analysis_id} needs a name in _ANALYSIS_NAMES"


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
