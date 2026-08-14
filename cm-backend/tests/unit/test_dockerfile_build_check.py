"""The Dockerfile's build-check against the service it checks. Inter-artifact pair, both ways.

===============================================================================================
WHY THIS FILE EXISTS BEFORE THE CHECK HAS EVER GONE STALE
===============================================================================================
synapse-ui-server has the same build-check and its list went stale TWICE, four days apart, both
times in exactly the way its own comment forbade. The rule was written down in the Dockerfile
before the second failure, which is the whole point: A RULE ENFORCED BY A HUMAN REMEMBERING IS
NOT ENFORCED, and this repository has no CI to notice otherwise.

The worse of that service's two failures produced NO SIGNAL AT ALL. A missing environment
variable fails the build loudly, because the app refuses to start. A route missing from the
asserted set does not: the check simply covers less than it claims, and three commits edited
that Dockerfile without anyone noticing two routes had gone unasserted for two days.

cm-backend is the service the entire console authenticates through, so the same silence here is
worse. cm-frontend's AuthBoundary hard-redirects to /auth/logout on a 401 from /me/permissions,
which means a cm-backend that ships without that route registered does not degrade: it logs
every user out.

===============================================================================================
IT PARSES THE DOCKERFILE. IT DOES NOT RESTATE IT.
===============================================================================================
There is no second copy of either set here. A hardcoded copy drifts exactly as the Dockerfile
would, and two artifacts disagreeing is harder to diagnose than one being stale: the reader has
to work out which is authoritative before working out which is wrong.

The other side of each comparison is the RUNNING ARTICLE, not a second parse. The env list is
checked against what Settings actually refuses to construct without, by removing names and
observing the refusal. The route set is checked against what the app actually registers,
through uvicorn's own importer on the Dockerfile's own ASGI_TARGET string.

===============================================================================================
THE .env FILE IS NEUTRALISED, AND THAT IS NOT TEST HYGIENE, IT IS THE POINT
===============================================================================================
Settings declares ``env_file = PROJECT_ROOT / ".env"``, and cm-backend/.env EXISTS on a
developer machine (gitignored, ~6KB, every value populated). Inside the image it does not:
.dockerignore excludes it, so the four variables in the build-check are the only source there.

Without disabling it, every test below would read that file, the omit-one-variable cases would
not refuse, and this suite would report health for a Dockerfile list that Cloud Build would
reject. That is the same shape as a developer's exported shell variable, one layer deeper and
harder to see, so the environment is replaced wholesale AND the file is switched off.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError
from uvicorn.importer import import_from_string

from admin_backend.config import Settings, get_settings

_DOCKERFILE = Path(__file__).resolve().parents[2] / "Dockerfile"

# One shell env assignment: either the first, on the RUN line itself, or a continued one
# indented beneath it. Anchored on the trailing backslash so a line that merely mentions a
# NAME="value" in prose cannot be read as part of the list.
_ENV_ASSIGNMENT = re.compile(r'^(?:RUN |[ \t]+)([A-Z][A-Z0-9_]*)="([^"]*)" \\$')

# The (path, method) literals inside the check's `required` set.
_ROUTE_LITERAL = re.compile(r"\('([^']+)', '([A-Z]+)'\)")

# The ASGI target the CMD and the build-check both read.
_ASGI_TARGET = re.compile(r'^ENV ASGI_TARGET="([^"]+)"$', re.MULTILINE)

# A router prefix: the first path segment under /api/v1, or the whole path for the handful of
# routes FastAPI mounts outside it.
_ROUTER_PREFIX = re.compile(r"^(/api/v1/[a-z0-9-]+)")

# VACUITY FLOORS. Not zero, and not the exact current numbers either. Zero is the failure these
# guard against; the exact number would be a third copy of the thing being checked, failing on
# every legitimate addition. These say "the parse clearly found the block", nothing more.
_MIN_ENV_NAMES = 3
_MIN_ROUTES = 10


def _dockerfile() -> str:
    return _DOCKERFILE.read_text(encoding="utf-8")


def _build_check_env() -> dict[str, str]:
    """The environment the build-check RUN step sets, parsed out of the Dockerfile.

    WALKS BACKWARDS FROM THE ``python -c`` LINE rather than forwards from a named variable. The
    first variable in the list is not special, and naming it here would break this parse the day
    somebody reorders the list.
    """
    lines = _dockerfile().splitlines()
    anchors = [i for i, line in enumerate(lines) if line.strip().startswith("python -c")]
    assert len(anchors) == 1, (
        f"expected exactly one `python -c` build-check line in the Dockerfile, found "
        f"{len(anchors)}. The parse below assumes one; two checks means this test is reading an "
        f"arbitrary one of them."
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
    """What the app actually registers, resolved the way uvicorn resolves it.

    THROUGH THE DOCKERFILE'S OWN ASGI_TARGET STRING and uvicorn's own importer, not through a
    direct ``from admin_backend.main import app``. A direct import would pass against a CMD that
    names an attribute which does not exist, which is the mismatch that shipped a dead image on
    synapse-ui-server.

    NOT CALLED AS A FACTORY, which is where this diverges from that service. cm-backend's target
    is ``main:app``, a module-level object built by ``app = create_app()`` at import time, so
    importing it IS building it. The caller must have installed the build-check environment
    first, for exactly that reason.
    """
    match = _ASGI_TARGET.search(_dockerfile())
    assert match is not None, "ENV ASGI_TARGET is gone from the Dockerfile; the CMD reads it too"
    app: Any = import_from_string(match.group(1))
    return {
        (route.path, method)
        for route in app.routes
        if hasattr(route, "path")
        for method in (getattr(route, "methods", None) or {"GET"})
    }


def _prefix(path: str) -> str:
    """The router a path belongs to, for the representative-per-router rule."""
    match = _ROUTER_PREFIX.match(path)
    return match.group(1) if match else path


@pytest.fixture
def build_check_env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Run under EXACTLY the Dockerfile's environment and nothing else.

    THREE THINGS, AND ALL THREE ARE REQUIRED:

      1. os.environ is REPLACED WHOLESALE rather than the named variables being set. A developer
         with DATABASE_URL exported would otherwise make the missing-variable case pass locally
         and fail in Cloud Build, which is the difference this file exists to close.
      2. Settings' ``env_file`` is switched off. cm-backend/.env exists locally and would supply
         every value; inside the image there is no such file. See the module docstring.
      3. get_settings' lru_cache is cleared on the way in AND on the way out. It is cached per
         process, so without this the first test to call it would freeze the answer for the rest
         of the session, and the leaked instance would follow this file into unrelated suites.
    """

    def under(env: dict[str, str]) -> None:
        monkeypatch.setattr(os, "environ", dict(env))
        monkeypatch.setitem(Settings.model_config, "env_file", None)
        get_settings.cache_clear()

    yield under
    get_settings.cache_clear()


@pytest.fixture
def registered_routes(build_check_env: Any) -> set[tuple[str, str]]:
    """The service's routes, built under the Dockerfile's own environment.

    DEPENDS ON build_check_env RATHER THAN THE AMBIENT ONE, so this is the app the BUILD builds
    and not the app a developer's shell and .env happen to allow. If the env list is short, this
    raises the same error Cloud Build would report, which is correct: an image whose module
    cannot be imported has no routes to assert.
    """
    build_check_env(_build_check_env())
    return _registered_routes()


# ---------------------------------------------------------------------------
# THE VACUITY GUARDS. These come first because every test below depends on them.
# ---------------------------------------------------------------------------


def test_the_dockerfile_is_where_this_test_thinks_it_is() -> None:
    assert _DOCKERFILE.is_file(), f"{_DOCKERFILE} not found"
    assert "admin_backend" in _dockerfile()


def test_the_env_parse_found_the_build_check_list() -> None:
    """IF THE PARSE FINDS NOTHING, EVERY COMPARISON BELOW IS VACUOUSLY TRUE.

    An empty dict satisfies "the Dockerfile provides everything Settings wants" only because
    Settings would refuse it, and satisfies "nothing here is unwanted" trivially. Absence is a
    failure, not a pass.
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
        f"parsed only {len(routes)} routes out of the Dockerfile's `required` set "
        f"({sorted(routes)}). The set moved or changed shape, and this file would be comparing "
        f"nothing."
    )


def test_the_service_registers_routes_at_all(registered_routes: set[tuple[str, str]]) -> None:
    """AND THE THIRD, on the side this file does not parse. If the app somehow registered
    nothing, the direction that matters most would report a clean bill of health."""
    assert len(registered_routes) >= _MIN_ROUTES


# ---------------------------------------------------------------------------
# THE ASGI TARGET, WHICH IS ONE STRING READ TWICE
# ---------------------------------------------------------------------------


def test_the_cmd_and_the_build_check_read_the_same_asgi_target() -> None:
    """THE DEAD-IMAGE CASE, AS A TEST. synapse-ui-server's CMD named one attribute and its check
    imported another; the check passed and the container died on startup. Here the CMD must
    reference the variable rather than repeat its value, so the two cannot diverge."""
    source = _dockerfile()
    match = _ASGI_TARGET.search(source)
    assert match is not None, "ENV ASGI_TARGET is gone"
    target = match.group(1)

    cmd_lines = [line for line in source.splitlines() if "uvicorn" in line and "exec" in line]
    assert len(cmd_lines) == 1, f"expected one uvicorn CMD line, found {len(cmd_lines)}"
    assert "$ASGI_TARGET" in cmd_lines[0], (
        f"the CMD does not read $ASGI_TARGET. It must reference the variable, not repeat "
        f"{target!r}: a second copy is a second thing to keep in step, and the last time this "
        f"estate wrote it twice the build passed and the container failed to start."
    )


def test_the_asgi_target_resolves_to_something_importable(
    registered_routes: set[tuple[str, str]],
) -> None:
    """Resolving it is the whole assertion; the fixture already did it through uvicorn's own
    importer. A target naming a missing attribute raises before this body runs."""
    assert registered_routes


# ---------------------------------------------------------------------------
# THE ENV LIST, BOTH DIRECTIONS
# ---------------------------------------------------------------------------


def test_the_build_check_env_is_enough_to_construct_settings(build_check_env: Any) -> None:
    """DIRECTION 1: the Dockerfile provides everything the service requires.

    Not a comparison against a list of names read out of config.py; it constructs the real
    Settings under the real parsed environment, so a field that becomes required through any
    mechanism at all is covered, not only one added to a literal this test might have parsed.

    A FAILURE HERE NAMES THE FIELD, because pydantic's ValidationError does. Add it to the
    Dockerfile's build-check list with a syntactically valid throwaway value.
    """
    build_check_env(_build_check_env())

    get_settings()  # raises ValidationError naming every missing field


@pytest.mark.parametrize("omitted", sorted(_build_check_env()))
def test_every_name_in_the_build_check_env_is_actually_required(
    build_check_env: Any, omitted: str
) -> None:
    """DIRECTION 2: the Dockerfile provides nothing the service does not require.

    PARAMETERISED SO THE FAILURE NAMES THE VARIABLE rather than reporting that the set has an
    extra member somewhere in it.

    Removing a genuinely required name must make Settings refuse. If it does not, that name is
    dead weight in the build check: somebody will maintain it believing it does something, and a
    value nothing reads is indistinguishable from a value read at a moment nobody expects. This
    is the direction that caught three stale entries on synapse-ui-server when slice 2 SHRANK
    its list, which a one-way assertion could never have seen.
    """
    env = _build_check_env()
    build_check_env({name: value for name, value in env.items() if name != omitted})

    with pytest.raises(ValidationError) as caught:
        get_settings()

    assert omitted.lower() in str(caught.value).lower(), (
        f"removing {omitted} made Settings refuse, but the error does not name it. Either the "
        f"variable is not the reason for the refusal, or the message no longer lists what is "
        f"missing, and an operator reading a failed build would be told the wrong thing."
    )


# ---------------------------------------------------------------------------
# THE ROUTE SET, BOTH DIRECTIONS
# ---------------------------------------------------------------------------


def test_every_router_has_a_representative_in_the_build_check(
    registered_routes: set[tuple[str, str]],
) -> None:
    """DIRECTION 1, AND THE ONE THAT PRODUCES NO SIGNAL WITHOUT THIS TEST.

    A router missing from `required` does not fail the build. The check passes, the image ships,
    and the assertion covers less than the comment above it claims.

    THE RULE IS ONE REPRESENTATIVE PER ROUTER, AND THE RULE IS WHAT IS ENFORCED, NOT THE LIST.
    This service registers 73 (path, method) pairs across 19 routers, 29 under /api/v1/tenants
    alone, so asserting every pair would be churn on every route added and a set nobody keeps.
    The realistic failure is a whole router failing to include, which takes all its paths at
    once, and that is what this catches. A hand-picked subset is what went wrong on
    synapse-ui-server: nobody decided /alerts was unimportant, they just never came back.
    """
    registered_prefixes = {_prefix(path) for path, _ in registered_routes}
    asserted_prefixes = {_prefix(path) for path, _ in _required_routes()}

    unrepresented = registered_prefixes - asserted_prefixes
    assert unrepresented == set(), (
        f"these routers have no representative in the Dockerfile's build check: "
        f"{sorted(unrepresented)}. Add one route from each to `required`. A router absent from "
        f"that set is a router the build would happily ship unregistered."
    )


def test_every_asserted_route_is_actually_registered(
    registered_routes: set[tuple[str, str]],
) -> None:
    """DIRECTION 2. A pair in `required` the service does not serve fails the BUILD, which is
    loud and fine, but it fails after a push rather than here. This is the same finding minutes
    earlier and without a wasted image.

    It also catches the subtler half: a path still served under a DIFFERENT METHOD. The set is
    compared as (path, method) pairs precisely so a POST that became a GET cannot satisfy an
    entry naming the path alone.
    """
    phantom = _required_routes() - registered_routes
    assert phantom == set(), (
        f"the Dockerfile's build check asserts routes the service does not register: "
        f"{sorted(phantom)}. Either they were renamed, or their method changed, or they were "
        f"removed and this set was not updated. The next build fails on exactly this."
    )


def test_the_two_routes_the_console_cannot_start_without_are_asserted() -> None:
    """NAMED EXPLICITLY, because their absence has a consequence the generic rule does not
    convey. /api/v1/health is what Cloud Run polls to decide a revision is live.
    /api/v1/me/permissions is what AuthBoundary calls at boot, and it hard-redirects to
    /auth/logout on a 401, so a build that shipped without it would log every user out rather
    than degrade. Both are covered by the per-router rule above; this says why they matter.
    """
    required = _required_routes()
    for pair in (("/api/v1/health", "GET"), ("/api/v1/me/permissions", "GET")):
        assert pair in required, (
            f"{pair} is no longer asserted by the Dockerfile's build check. The per-router rule "
            f"may still be satisfied by a sibling route, which is why this is checked by name."
        )
