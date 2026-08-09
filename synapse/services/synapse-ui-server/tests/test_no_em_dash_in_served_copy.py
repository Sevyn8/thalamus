"""No em-dash may reach a user through copy this service authors.

WHY A TEST AND NOT A CONVENTION. The rule is old; the enforcement is not. A frontend scan run
during B2b-1 found nine rendered em-dashes in TypeScript literals and reported zero remaining,
which was true and read as "the console is clean". It was not: the longest em-dash-bearing
strings on the whole console were arriving from THIS service, in Threshold.stands_in_for and
_DECLINED's reason, and a frontend grep cannot see them. The scan was not wrong, it was blind to
a category, and nothing said so.

TWO HALVES, AND NEITHER IS SUFFICIENT ALONE:

  - this file walks the copy the BFF serves and the console RENDERS
  - cm-frontend/scripts/assert-no-em-dash.mjs walks TypeScript literals, wired into `pnpm build`

There is no CI in this repository, so a check nobody runs is worth nothing. Both halves hang off
a command somebody already runs: `make -C synapse test` and `pnpm build`.

===============================================================================================
THE RULE GOVERNS OUTPUT, NOT INTERNAL REASONING
===============================================================================================
``Threshold.stands_in_for`` and ``_DECLINED``'s reason are still SERVED and no longer RENDERED.
Four of the six stands_in_for values contain an em-dash and they keep it: it is a reviewer's
argument, the audience the rule protects never sees it, and rewriting prose nobody reads to
satisfy a typographic rule would be the tail wagging the dog. They are deliberately absent from
the walk below, and ``test_the_unrendered_fields_are_deliberately_excluded`` records that as a
decision rather than leaving it as an omission somebody later reads as an oversight.

IF THE CONSOLE EVER RENDERS THEM AGAIN, move them into _rendered_copy in the same commit.

===============================================================================================
WHAT THIS CANNOT SEE. Stated, not papered over.
===============================================================================================

1. CUSTOMER DATA. tenant_name, product_name and store_name come from identity_mirror and
   canonical. A product named with an em-dash renders one. Not our copy, and no rule here can
   reach it.

2. synapse.run.detail. Free text the ORCHESTRATOR writes at runtime, largely exception text.
   It reaches the console on AnalysisState.detail and is rendered nowhere, which is why it is
   not a live leak. A static walk cannot inspect a value that does not exist until a run fails.
   See the comment on reads.AnalysisState.detail.

3. ERROR STRINGS ON THE FAILURE PATH. HTTPException detail, and the message the console shows
   through SynapseDown. Authored here and currently clean, but they are raised rather than
   returned by the catalogue functions walked below, so nothing here would notice one appearing.

4. ANY CATALOGUE NOT IN THE WALK. _WALKED names the covered surfaces explicitly and a guard
   below fails if catalog grows a third, because an uncovered surface passing silently is the
   failure mode that let a source-scraping regex in test_grants_cover_reads fall from nine
   objects to four with every assertion still green.
"""

from __future__ import annotations

from synapse_ui_server import catalog

EM_DASH = "—"

# The catalogue surfaces this service authors copy for. Named explicitly so adding a third is a
# visible edit here rather than a silent gap; see blind spot 4.
_WALKED = frozenset({"analyses", "capabilities"})


def _rendered_copy() -> list[tuple[str, str]]:
    """Every string the catalogue serves AND the console draws, as (where, text)."""
    out: list[tuple[str, str]] = []
    # Distinct loop variables: reusing one name makes mypy narrow it to the first type and
    # reject every attribute of the second.
    for analysis in catalog.analyses():
        out.append((f"analyses[{analysis.analysis_id}].name", analysis.name))
        for threshold in analysis.thresholds:
            where = f"analyses[{analysis.analysis_id}].thresholds[{threshold.name}]"
            out.append((f"{where}.description", threshold.description))
    for capability in catalog.capabilities():
        out.append((f"capabilities[{capability.capability_id}].name", capability.name))
        if capability.declined_summary:
            out.append(
                (
                    f"capabilities[{capability.capability_id}].declined_summary",
                    capability.declined_summary,
                )
            )
    return out


def test_the_walk_actually_collected_something() -> None:
    """VACUITY GUARD. Every assertion below is over this list; a walk that silently stops
    collecting turns the whole file green while checking nothing."""
    collected = _rendered_copy()
    assert len(collected) >= 12, (
        f"the walk collected only {len(collected)} strings, fewer than the six threshold "
        f"descriptions plus two analysis names plus four capability names. It has stopped "
        f"biting. Walked: {sorted(_WALKED)}"
    )


def test_the_walk_covers_every_catalogue_surface() -> None:
    """Blind spot 4, made loud. catalog exposes exactly two public generators today; a third
    would serve copy nothing here inspects, and this fails until it is added to _WALKED and to
    _rendered_copy."""
    # DEFINED HERE, not merely visible here. catalog imports declaration_for, registered_ids and
    # friends from synapse.registry, and those land in its namespace without being surfaces it
    # serves copy through. Filtering on __module__ is what separates the two.
    public = {
        name
        for name in dir(catalog)
        if not name.startswith("_")
        and name.islower()
        and callable(getattr(catalog, name))
        and getattr(getattr(catalog, name), "__module__", None) == catalog.__name__
    }
    assert public == _WALKED, (
        f"catalog's public surface is {sorted(public)} but the walk covers {sorted(_WALKED)}. "
        "Add the new one to _rendered_copy and _WALKED, or this check is now partial."
    )


def test_no_rendered_string_carries_an_em_dash() -> None:
    """THE RULE. An em-dash in copy this service authors reaches an operator's screen."""
    offenders = [(where, text) for where, text in _rendered_copy() if EM_DASH in text]
    assert not offenders, "em-dash in rendered copy:\n" + "\n".join(
        f"  {where}: ...{text[max(0, text.index(EM_DASH) - 40) : text.index(EM_DASH) + 40]}..."
        for where, text in offenders
    )


def test_the_unrendered_fields_are_deliberately_excluded() -> None:
    """THE DECISION, RECORDED. stands_in_for and declined_reason keep their em-dashes because
    nothing draws them. This asserts the premise that makes that safe: they still carry em-dashes
    AND they are still served. If a future slice cleans them anyway, this fails and the comment
    above gets revisited rather than quietly becoming untrue.
    """
    with_em_dash = [
        t.stands_in_for
        for row in catalog.analyses()
        for t in row.thresholds
        if t.stands_in_for and EM_DASH in t.stands_in_for
    ]
    assert with_em_dash, (
        "no stands_in_for carries an em-dash any more. Either the declarations were rewritten, "
        "in which case delete this test and the exclusion it documents, or the field stopped "
        "being served, in which case the walk above should be checking it."
    )
    assert any(row.declined_reason for row in catalog.capabilities() if not row.resolves), (
        "declined_reason is no longer served; the exclusion documented above is now moot"
    )
