"""No em-dash may LEAVE THE PLATFORM in a message Axon sends.

WHY A THIRD GUARD. There are already two and neither can see this:

  - cm-frontend/scripts/assert-no-em-dash.mjs walks TypeScript literals under the Synapse
    console roots, wired into `pnpm build`.
  - synapse-ui-server/tests/test_no_em_dash_in_served_copy.py walks the copy the BFF serves and
    the console RENDERS, wired into `make -C synapse test`.

IT LIVES IN THIS SUITE RATHER THAN IN axon/tests, AND THAT IS THE WHOLE POINT OF WHERE IT SITS.
The copy it walks is composed HERE, in synapse_ui_server.main, because Axon renders nothing: the
port takes an already-composed body. And `make -C synapse test` is a command somebody already
runs, while axon/tests needs its own invocation. A guard nobody runs is worth nothing, which is
the reason both existing halves hang off commands that were already in use.

Mail is a third category, and it is the only one of the three that leaves the estate. A rendered
email is read in somebody's inbox with no console styling, no theme and no reviewer between the
string and the reader. The frontend scan cannot see it because it is Python; the served-copy scan
cannot see it because the console never renders it.

That is the same shape as the miss the served-copy file records: a frontend scan reported zero
em-dashes remaining, which was true and read as "clean", while the longest em-dash-bearing
strings on the console were arriving from the BFF. A scan is not wrong when it is blind to a
category. It is wrong when nothing says so.

===============================================================================================
WHAT THIS CANNOT SEE. Stated, not papered over.
===============================================================================================

1. WHAT A PRODUCER PASSES IN. Axon renders nothing: `Message.body` arrives already composed, and
   this walks the ONE composer that exists today. A second producer composing its own body is
   outside this file's reach, and the fix when that happens is to walk it here too, in the same
   commit that adds it.

2. CUSTOMER AND TENANT DATA. A tenant named with an em-dash renders one. Not our copy, and no
   rule here can reach it.

3. WHAT A PROVIDER DOES TO A STRING IN TRANSIT. Nothing in this repository can observe that.
"""

from __future__ import annotations

import inspect
from pathlib import Path

import pytest

EM_DASH = "—"

# THE ONE COMPOSER THAT EXISTS. Imported rather than read as text so that a rename breaks this
# test loudly instead of leaving it walking a function that no longer exists.
from synapse_ui_server.main import _enablement_email_body  # noqa: E402


def _rendered_copy() -> list[tuple[str, str]]:
    """Every string this platform would put in front of a human, with a label for the failure.

    EXERCISED, NOT PARSED. The body is assembled from branches, and a static read of the source
    would miss a string built by concatenation. Calling it across every branch is what makes the
    walk cover what a reader would actually receive.
    """
    common = {
        "tenant_name": "TestCo",
        "analysis_id": "dead_stock",
        "timezone": "Asia/Kolkata",
        "actor_subject": "auth0|operator",
    }
    return [
        (
            "enablement body, fresh insert",
            _enablement_email_body(**common, already_provisioned=False, warning=None),
        ),
        (
            "enablement body, already provisioned",
            _enablement_email_body(**common, already_provisioned=True, warning=None),
        ),
        (
            "enablement body, with the zero-positions warning",
            _enablement_email_body(
                **common,
                already_provisioned=False,
                warning='"TestCo" has no canonical positions. Enabled anyway.',
            ),
        ),
    ]


def test_the_walk_covers_something() -> None:
    """THE VACUITY GUARD, and the other two guards each have one for the same reason.

    A walk over an empty list passes. If the composer is renamed, moved or deleted and this file
    is left behind, every assertion below becomes 0 == 0 and reports a clean result for a rule it
    is no longer enforcing. Absence is a failure here, not a pass.
    """
    copy = _rendered_copy()
    assert copy, "the walk found no copy at all; it has stopped covering anything"
    assert len(copy) >= 3, "the branch coverage shrank; a branch's copy is no longer walked"
    for label, text in copy:
        assert text.strip(), f"{label} rendered empty, so scanning it proves nothing"


def test_no_em_dash_reaches_an_inbox() -> None:
    """THE RULE. It governs OUTPUT, and mail is the output that travels furthest."""
    offenders = [label for label, text in _rendered_copy() if EM_DASH in text]
    assert offenders == [], (
        f"an em-dash would reach somebody's inbox from: {offenders}. Neither existing guard can "
        "see this string: one walks TypeScript, the other walks what the console renders."
    )


def test_the_composer_is_the_only_one_and_this_test_knows_where_it_lives() -> None:
    """A SECOND COMPOSER WOULD BE INVISIBLE TO THIS FILE, so the file says how to notice one.

    Asserted on the module rather than trusted: if the body helper moves out of main.py, this
    fails and whoever moved it is told to bring the walk along.
    """
    module = inspect.getmodule(_enablement_email_body)
    assert module is not None
    assert module.__name__ == "synapse_ui_server.main", (
        "the enablement body composer moved. Update _rendered_copy above in the same commit, or "
        "this guard walks a function nobody calls."
    )


# EVERY DIRECTORY AXON AUTHORS PYTHON IN. The list has grown before and the growth is the point:
# it once read ["axon/src/axon", "axon/tests"] when axon was a library with no services, and a new
# service under axon/services/ would have sat outside it. That is the SAME MISS as
# cm-frontend/scripts/assert-no-em-dash.mjs's root list, which covered three Synapse directories
# and would have covered a new lib/axon with nothing while its total stayed above the floor.
#
# CAUGHT BEFORE THE SERVICE EXISTED RATHER THAN AFTER, which is the only version of this that is
# worth anything: a root list updated when somebody notices the gap has already been wrong for
# however long the gap was there.
_AXON_ROOTS = ["axon/src/axon", "axon/tests", "axon/services"]


@pytest.mark.parametrize("root", _AXON_ROOTS)
def test_axon_authors_no_em_dash_in_its_own_source(root: str) -> None:
    """AND THE MODULE'S OWN FILES, comments included.

    BROADER THAN THE OUTPUT RULE ON PURPOSE, and narrower in scope than the served-copy test's
    equivalent: that file deliberately EXEMPTS prose nobody renders, because rewriting a
    reviewer's argument to satisfy a typographic rule is the tail wagging the dog. Axon has no
    such body of reviewer prose yet, so the whole module is held to the stricter rule while that
    is still cheap. If a genuinely unrendered argument ever needs the character, exempt it here
    deliberately rather than deleting the check.
    """
    # tests/ -> synapse-ui-server -> services -> synapse -> the monorepo root
    repo_root = Path(__file__).resolve().parents[4]
    directory = repo_root / root
    assert directory.is_dir(), f"{directory} not found; this guard has stopped biting"

    # THE VACUITY GUARD, PER ROOT AND NOT ACROSS THE SET. A root that resolves but holds no
    # Python passes every assertion below having read nothing, and reads as coverage. That is
    # exactly the failure assert-no-em-dash.mjs once had: it checked a TOTAL across
    # roots, so three large directories carried a fourth that was empty or misspelled.
    scanned = sorted(directory.rglob("*.py"))
    assert scanned, (
        f"{directory} contains no .py files. Either the directory moved or this root covers "
        "nothing, and every check below would pass having read nothing."
    )

    offenders = [
        str(path.relative_to(repo_root))
        for path in scanned
        # THIS FILE IS EXCLUDED, AND THE REASON IS THE GUARD ITSELF. It has to contain the
        # character in order to search for it, so scanning itself reports the machinery as the
        # offence. That is the same shape the Terraform posture test records when it strips
        # lifecycle blocks before scanning for allUsers: a guard that names what it forbids
        # cannot be scanned by its own rule. Caught by running it, not by reading it.
        if path != Path(__file__).resolve()
        if EM_DASH in path.read_text(encoding="utf-8")
    ]
    assert offenders == [], f"em-dash in Axon source: {offenders}"
