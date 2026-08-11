"""The Dockerfile's build-check against the service it checks. Inter-artifact pair, both ways.

===============================================================================================
WHY THIS FILE EXISTS: THE RULE WAS ALREADY WRITTEN DOWN AND WAS STILL NOT FOLLOWED
===============================================================================================
The Dockerfile has said, since v6, "A variable added to load_config() must be added here in the
same commit". It said so BEFORE v15 failed in Cloud Build with

    RuntimeError: synapse-ui-server cannot start; missing AXON_READER_URL

which is the same failure v6 had, in the same place, with the same message shape. A RULE
ENFORCED BY A HUMAN REMEMBERING IS NOT ENFORCED, and this repository has no CI to notice
otherwise.

THE ROUTE SET HAD DRIFTED FURTHER AND MORE QUIETLY. The env list fails loudly at build time
because load_config refuses to start. The route set does not: a route missing from `required` is
simply not asserted, so the check passes while covering less than it claims. When this file was
written the Dockerfile asserted 13 routes and the service served 16. /alerts and
/alerts/state-counts, the console's busiest read surface, had been unasserted since 2026-08-09,
and THREE commits edited the Dockerfile after they landed without anyone noticing. That is the
worse of the two failures and it is the one that produced no signal at all.

===============================================================================================
IT PARSES THE DOCKERFILE. IT DOES NOT RESTATE IT.
===============================================================================================
There is no second copy of either set in this file. A hardcoded copy would drift exactly as the
Dockerfile did, and two artifacts disagreeing is harder to diagnose than one being stale: the
reader has to work out which is authoritative before they can work out which is wrong.

AND THE OTHER SIDE OF EACH COMPARISON IS THE RUNNING ARTICLE, NOT A PARSE EITHER. The env list
is checked against what ``load_config()`` actually refuses to start without, by removing names
and observing the refusal. The route set is checked against what ``create_app()`` actually
registers, through uvicorn's own importer on the Dockerfile's own ASGI_TARGET string. So the
only thing either test knows by hand is where to look.

BOTH DIRECTIONS, ALWAYS. A name in the Dockerfile the service does not want is as wrong as one
it wants and the Dockerfile lacks: the first is a value somebody will maintain believing it does
something, and it is how SYNAPSE_WRITER_URL would arrive here to "make the check pass" and break
every real revision.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from synapse_ui_server.config import load_config
from uvicorn.importer import import_from_string

_DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"

# One shell env assignment: either the first, on the RUN line itself, or a continued one
# indented beneath it. Anchored on the trailing backslash so a line that merely mentions a
# NAME="value" in prose cannot be read as part of the list.
_ENV_ASSIGNMENT = re.compile(r'^(?:RUN |[ \t]+)([A-Z][A-Z0-9_]*)="([^"]*)" \\$')

# The (path, method) literals inside the check's `required` set.
_ROUTE_LITERAL = re.compile(r"\('([^']+)', '([A-Z]+)'\)")

# The ASGI target the CMD and the build-check both read.
_ASGI_TARGET = re.compile(r'^ENV ASGI_TARGET="([^"]+)"$', re.MULTILINE)

# VACUITY FLOORS. Not zero, and not the exact current numbers either. Zero is the failure these
# guard against; the exact number would be a third copy of the thing being checked, failing on
# every legitimate addition. These are "the parse clearly found the block", nothing more.
_MIN_ENV_NAMES = 5
_MIN_ROUTES = 5


def _dockerfile() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


def _build_check_env() -> dict[str, str]:
    """The environment the build-check RUN step sets, parsed out of the Dockerfile.

    WALKS BACKWARDS FROM THE `python -c` LINE rather than forwards from a named variable. The
    first variable in the list is not special and naming it here would make this parse break the
    day somebody reorders the list alphabetically.
    """
    lines = _dockerfile().splitlines()
    anchors = [i for i, line in enumerate(lines) if line.strip().startswith("python -c")]
    assert len(anchors) == 1, (
        f"expected exactly one `python -c` build-check line in the Dockerfile, found "
        f"{len(anchors)}. The parse below assumes one; two checks means this test is reading "
        f"an arbitrary one of them."
    )

    env: dict[str, str] = {}
    index = anchors[0] - 1
    while index >= 0:
        match = _ENV_ASSIGNMENT.match(lines[index])
        if match is None:
            break
        env[match.group(1)] = match.group(2)
        index -= 1
    return env


def _required_routes() -> set[tuple[str, str]]:
    """The (path, method) pairs the build-check asserts, parsed out of the Dockerfile."""
    source = _dockerfile()
    start = source.index("required = {")
    end = source.index("missing = required - routes")
    return {(path, method) for path, method in _ROUTE_LITERAL.findall(source[start:end])}


def _registered_routes() -> set[tuple[str, str]]:
    """What create_app() actually registers, resolved the way uvicorn resolves it.

    THROUGH THE DOCKERFILE'S OWN ASGI_TARGET STRING and uvicorn's own importer, not through a
    direct import of create_app. A direct import would pass against a Dockerfile whose CMD names
    an attribute that does not exist, which is a mismatch that shipped a dead image once.

    THE CALLER MUST HAVE INSTALLED THE BUILD-CHECK ENVIRONMENT FIRST. The factory takes no
    arguments, so it goes through load_config, exactly as `uvicorn --factory` does. That is not
    an inconvenience to work around: it is the reason the env list and the route set are one
    contract rather than two, and it is why a missing variable takes the route assertions down
    with it.
    """
    match = _ASGI_TARGET.search(_dockerfile())
    assert match is not None, "ENV ASGI_TARGET is gone from the Dockerfile; the CMD reads it too"
    factory: Any = import_from_string(match.group(1))
    app = factory()
    return {
        (route.path, method)
        for route in app.routes
        if hasattr(route, "path")
        for method in (getattr(route, "methods", None) or {"GET"})
    }


@pytest.fixture
def build_check_env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Run a callable under EXACTLY the Dockerfile's environment and nothing else.

    os.environ IS REPLACED WHOLESALE rather than the named variables being set. A developer with
    AXON_READER_URL exported in their shell would otherwise make the missing-variable case pass
    locally and fail in Cloud Build, which is precisely the difference this file exists to close.
    """

    def under(env: dict[str, str]) -> None:
        monkeypatch.setattr(os, "environ", dict(env))

    return under


@pytest.fixture
def registered_routes(build_check_env: Any) -> set[tuple[str, str]]:
    """The service's routes, built under the Dockerfile's own environment.

    DEPENDS ON build_check_env RATHER THAN THE AMBIENT ONE, so this is the app the BUILD builds
    and not the app a developer's shell happens to allow. If the env list is short, this fixture
    raises the same RuntimeError Cloud Build reports, which is correct: an image whose factory
    cannot be called has no routes to assert.
    """
    build_check_env(_build_check_env())
    return _registered_routes()


# ---------------------------------------------------------------------------
# THE VACUITY GUARDS. These come first because every test below depends on them.
# ---------------------------------------------------------------------------


def test_the_dockerfile_is_where_this_test_thinks_it_is() -> None:
    assert _DOCKERFILE.is_file(), f"{_DOCKERFILE} not found"
    assert "synapse-ui-server" in _dockerfile()


def test_the_env_parse_found_the_build_check_list() -> None:
    """IF THE PARSE FINDS NOTHING, EVERY COMPARISON BELOW IS VACUOUSLY TRUE.

    An empty dict satisfies "the Dockerfile provides everything load_config wants" only because
    load_config would refuse it, and satisfies "nothing here is unwanted" trivially. That is the
    exact shape that let test_grants_cover_reads report health while covering four objects
    instead of nine, and that let assert-no-em-dash cover a whole directory with nothing while
    its total stayed above the floor. Absence is a failure, not a pass.
    """
    env = _build_check_env()
    assert len(env) >= _MIN_ENV_NAMES, (
        f"parsed only {len(env)} environment names out of the Dockerfile's build check "
        f"({sorted(env)}). The RUN block moved or changed shape, and the comparisons in this "
        f"file would pass having checked almost nothing."
    )


def test_the_route_parse_found_the_required_set() -> None:
    """The same guard for the other half. A `required` set that parsed as empty would make the
    Dockerfile's own assertion vacuous AND this file's comparison vacuous at once."""
    routes = _required_routes()
    assert len(routes) >= _MIN_ROUTES, (
        f"parsed only {len(routes)} routes out of the Dockerfile's `required` set ({sorted(routes)}). "
        f"The set moved or changed shape, and this file would be comparing nothing."
    )


def test_the_service_registers_routes_at_all(registered_routes: set[tuple[str, str]]) -> None:
    """AND THE THIRD, on the side this file does not parse. If create_app() somehow registered
    nothing, the direction that matters most would report a clean bill of health."""
    assert len(registered_routes) >= _MIN_ROUTES


# ---------------------------------------------------------------------------
# THE ENV LIST, BOTH DIRECTIONS
# ---------------------------------------------------------------------------


def test_the_build_check_env_is_enough_for_load_config(build_check_env: Any) -> None:
    """DIRECTION 1: the Dockerfile provides everything the service requires.

    THIS IS THE v15 FAILURE, AS A TEST. It is not a comparison against a list of names read out
    of config.py; it runs the real load_config under the real parsed environment, so a variable
    that becomes required through any mechanism at all is covered, not only one added to the
    literal this test might otherwise have parsed.

    A FAILURE HERE NAMES THE VARIABLE, because load_config's own error does. Add it to the
    Dockerfile's build-check list with a syntactically valid throwaway value.
    """
    env = _build_check_env()
    build_check_env(env)

    load_config()  # raises RuntimeError naming every missing variable


@pytest.mark.parametrize("omitted", sorted(_build_check_env()))
def test_every_name_in_the_build_check_env_is_actually_required(build_check_env: Any, omitted: str) -> None:
    """DIRECTION 2: the Dockerfile provides nothing the service does not require.

    PARAMETERISED SO THE FAILURE NAMES THE VARIABLE rather than reporting that the set has an
    extra member somewhere in it.

    Removing a genuinely required name must make load_config refuse. If it does not, that name
    is dead weight in the build check: somebody will maintain it believing it does something, and
    a value nothing reads is indistinguishable from a value read at a moment nobody expects.

    THIS IS ALSO WHAT KEEPS SYNAPSE_WRITER_URL OUT without naming it. load_config REFUSES when
    the writer DSN is set, so adding it to the build-check list to "make the check pass" fails
    direction 1 above immediately.
    """
    env = _build_check_env()
    reduced = {name: value for name, value in env.items() if name != omitted}
    build_check_env(reduced)

    with pytest.raises(RuntimeError) as caught:
        load_config()

    assert omitted in str(caught.value), (
        f"removing {omitted} made load_config fail, but the error does not name it. Either the "
        f"variable is not the reason for the refusal, or the message no longer lists what is "
        f"missing, and an operator reading a failed build would be told the wrong thing."
    )


# ---------------------------------------------------------------------------
# THE ROUTE SET, BOTH DIRECTIONS
# ---------------------------------------------------------------------------


def test_every_registered_route_is_asserted_by_the_build_check(
    registered_routes: set[tuple[str, str]],
) -> None:
    """DIRECTION 1, AND THE ONE THAT PRODUCES NO SIGNAL WITHOUT THIS TEST.

    A route missing from `required` does not fail the build. The check passes, the image ships,
    and the assertion covers less than the comment above it claims. When this file was written
    three routes were in exactly that state, two of them for two days across three edits of the
    Dockerfile.

    THE STANDARD IS EVERY ROUTE, NOT EVERY IMPORTANT ROUTE. A sampled set is a set somebody has
    to keep making a judgement about, and the judgement is what went wrong: nobody decided
    /alerts was unimportant, they just never came back here.
    """
    unasserted = registered_routes - _required_routes()
    assert unasserted == set(), (
        f"the service registers routes the Dockerfile's build check does not assert: "
        f"{sorted(unasserted)}. Add them to `required`. A route absent from that set is a route "
        f"the build would happily ship unregistered."
    )


def test_every_asserted_route_is_actually_registered(
    registered_routes: set[tuple[str, str]],
) -> None:
    """DIRECTION 2. A pair in `required` that the service does not serve fails the BUILD, which
    is loud and fine, but it fails it in Cloud Build after a push rather than here. This is the
    same finding four minutes earlier and without a wasted image.

    It also catches the subtler half: a path that is still served under a DIFFERENT METHOD. The
    set is compared as (path, method) pairs precisely so a POST that became a GET cannot satisfy
    an entry naming the path alone.
    """
    phantom = _required_routes() - registered_routes
    assert phantom == set(), (
        f"the Dockerfile's build check asserts routes the service does not register: "
        f"{sorted(phantom)}. Either they were renamed, or their method changed, or they were "
        f"removed and this set was not updated. The next build fails on exactly this."
    )
