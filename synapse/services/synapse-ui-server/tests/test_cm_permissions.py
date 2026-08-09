"""The provisioning gate: it asks Customer Master, and it denies on every kind of doubt.

WHY MOST OF THIS FILE IS FAILURE MODES. A permission check has one interesting success path and
about eight ways to accidentally become decoration, and every one of them looks like defensive
code while it is being written. `except Exception: return True` is the whole vulnerability, and a
suite that tested only the happy path and a clean denial would pass against it.

So the deny cases are enumerated one per test rather than parametrised into a single "it denies"
assertion. When one of them regresses, the failing test names which one, and the reason a CM
outage must deny is not the same reason a malformed body must deny.

THE PERMISSION IS KNOWN-BROADER THAN THE ACT and that is a deliberate, recorded, temporary
decision with a production condition attached. There is a test for the paragraph, below, because
the condition is the only thing standing between a staging-acceptable gate and a real customer's
configuration sitting behind a permission that means something else.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import httpx
import pytest
from synapse_ui_server import cm_permissions
from synapse_ui_server.cm_permissions import can_configure_tenants

BASE = "https://cm.example.run.app"
TOKEN = "a-real-looking-token"


class _FakeResponse:
    def __init__(self, status_code: int, payload: Any = None, *, text: str | None = None) -> None:
        self.status_code = status_code
        self._payload = payload
        self._text = text

    def json(self) -> Any:
        if self._text is not None:
            raise ValueError("not json")
        return self._payload


class _FakeClient:
    """Stands in for httpx.AsyncClient, recording the one call the gate makes.

    RECORDS THE REQUEST as well as answering it. Several of the tests below are about WHAT was
    sent rather than what came back: the tuple, the forwarded token, and the timeout are each
    load-bearing and each invisible to a test that only inspects the return value.
    """

    last: dict[str, Any] = {}

    def __init__(self, response: Any = None, raises: Exception | None = None, **kwargs: Any) -> None:
        self._response = response
        self._raises = raises
        _FakeClient.last = {"init": kwargs}

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, url: str, params: Any = None, headers: Any = None) -> Any:
        _FakeClient.last.update({"url": url, "params": params, "headers": headers})
        if self._raises is not None:
            raise self._raises
        return self._response


def _install(
    monkeypatch: pytest.MonkeyPatch, *, response: Any = None, raises: Exception | None = None
) -> None:
    """Patch the AsyncClient AT cm_permissions, so the module's own call site is under test."""

    def factory(**kwargs: Any) -> _FakeClient:
        return _FakeClient(response=response, raises=raises, **kwargs)

    monkeypatch.setattr(cm_permissions.httpx, "AsyncClient", factory)


# ---------------------------------------------------------------------------
# THE ONE WAY IN
# ---------------------------------------------------------------------------


async def test_a_200_with_allowed_true_permits(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE BASELINE, and without it every denial test below would pass against a gate that
    refused everybody, which is a gate nobody would notice was broken until an operator tried to
    enable something."""
    _install(monkeypatch, response=_FakeResponse(200, {"allowed": True, "reason_code": "GRANT_MATCHED"}))
    assert await can_configure_tenants(base_url=BASE, bearer=TOKEN) is True


async def test_it_asks_for_exactly_admin_tenants_configure_global(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE TUPLE, ASSERTED ON THE WIRE.

    CM validates each of the four query parameters against its own Postgres enum and answers 422
    on an unknown member, so a typo here does not silently match nothing: it becomes a non-200 and
    the gate denies everybody. That failure is safe and completely opaque, which is why the
    request is pinned rather than trusted.

    NO target_anchor. It is an ltree path for the TENANT cascade and CM documents it as ignored on
    the PLATFORM path, which is the only path a caller here can be on.
    """
    _install(monkeypatch, response=_FakeResponse(200, {"allowed": True}))
    await can_configure_tenants(base_url=BASE, bearer=TOKEN)

    assert _FakeClient.last["params"] == {
        "module": "ADMIN",
        "resource": "TENANTS",
        "action": "CONFIGURE",
        "scope": "GLOBAL",
    }
    assert _FakeClient.last["url"] == f"{BASE}/api/v1/me/can-do"


async def test_it_forwards_the_callers_own_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE WHOLE POINT IS THAT CM ANSWERS FOR THIS PERSON.

    A service-to-service credential here would ask "may synapse-ui-server configure tenants",
    which is a question with a useless answer: the gate would be constant and every operator would
    inherit it. Both services verify the same Auth0 access token, so forwarding is possible and is
    the only construction that means anything.
    """
    _install(monkeypatch, response=_FakeResponse(200, {"allowed": True}))
    await can_configure_tenants(base_url=BASE, bearer=TOKEN)

    assert _FakeClient.last["headers"] == {"Authorization": f"Bearer {TOKEN}"}


async def test_the_call_is_bounded_by_a_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    """A WRITE PATH WAITING ON A SECOND SERVICE NEEDS A CEILING, or Cloud Run's own request
    timeout is the only bound and an operator cannot tell a slow gate from a hung one."""
    _install(monkeypatch, response=_FakeResponse(200, {"allowed": True}))
    await can_configure_tenants(base_url=BASE, bearer=TOKEN)

    assert _FakeClient.last["init"]["timeout"] == cm_permissions._TIMEOUT_SECONDS
    assert 0 < cm_permissions._TIMEOUT_SECONDS <= 10


# ---------------------------------------------------------------------------
# EVERY OTHER WAY DENIES. One test each, because the reasons differ.
# ---------------------------------------------------------------------------


async def test_a_clean_denial_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """The ordinary case: CM answered, and the answer is no."""
    _install(
        monkeypatch,
        response=_FakeResponse(200, {"allowed": False, "reason_code": "NO_MATCHING_GRANT_OR_OUT_OF_SCOPE"}),
    )
    assert await can_configure_tenants(base_url=BASE, bearer=TOKEN) is False


async def test_a_timeout_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """THE ONE THAT MATTERS MOST, because it is the one an outage produces and the one where
    failing open would feel reasonable at 2am. A denial during a CM outage is a visible,
    temporary, correct refusal; the alternative is a window in which anybody who can reach the
    console can change a customer's configuration."""
    _install(monkeypatch, raises=httpx.ReadTimeout("too slow"))
    assert await can_configure_tenants(base_url=BASE, bearer=TOKEN) is False


async def test_a_connection_error_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """DNS, a reset, a TLS failure, CM scaled to zero and cold. Same answer."""
    _install(monkeypatch, raises=httpx.ConnectError("no route"))
    assert await can_configure_tenants(base_url=BASE, bearer=TOKEN) is False


@pytest.mark.parametrize("status", [401, 403, 404, 422, 500, 502, 503])
async def test_every_non_200_denies(monkeypatch: pytest.MonkeyPatch, status: int) -> None:
    """404 IS IN THIS LIST DELIBERATELY. It is what a wrong CM_API_BASE_URL or a renamed path
    produces, and it is the failure most likely to arrive from a config change rather than an
    outage. Treating "the endpoint is not there" as anything but a denial would mean a typo in
    terraform silently removes the gate."""
    _install(monkeypatch, response=_FakeResponse(status, {"allowed": True}))
    assert await can_configure_tenants(base_url=BASE, bearer=TOKEN) is False


async def test_a_non_json_body_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    """A 200 carrying HTML is what a proxy or a login redirect looks like, and it is not consent."""
    _install(monkeypatch, response=_FakeResponse(200, text="<html>sign in</html>"))
    assert await can_configure_tenants(base_url=BASE, bearer=TOKEN) is False


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"reason_code": "GRANT_MATCHED"},
        {"allowed": None},
        {"allowed": "true"},
        {"allowed": "false"},
        {"allowed": 1},
        [],
        "allowed",
        None,
    ],
)
async def test_a_body_that_does_not_say_allowed_true_denies(
    monkeypatch: pytest.MonkeyPatch, payload: Any
) -> None:
    """`is True`, NOT TRUTHINESS, and the string cases are why.

    {"allowed": "false"} is a truthy value meaning the opposite of itself, and it is exactly the
    shape a serialisation bug produces. {"allowed": 1} is what a client library that coerces bools
    to ints sends. Both would pass `if body.get("allowed")` and neither is CM saying yes.
    """
    _install(monkeypatch, response=_FakeResponse(200, payload))
    assert await can_configure_tenants(base_url=BASE, bearer=TOKEN) is False


# ---------------------------------------------------------------------------
# THE PRODUCTION CONDITION
# ---------------------------------------------------------------------------


def test_the_known_broader_condition_is_recorded_in_the_module() -> None:
    """THE PARAGRAPH IS THE ARTIFACT, so the test guards the paragraph.

    ADMIN.TENANTS.CONFIGURE.GLOBAL is TRUE of this act and BROADER than it: anyone who may
    configure a tenant may now enable a Synapse analysis for it. That was accepted knowingly
    because it is a real CM permission, duplicates no part of CM's model, and is one line to
    change. The correct answer is a SYNAPSE module and a PROVISION resource in CM's enums, which
    is a Customer Master slice because both vocabularies are locked Postgres enums there.

    THE CONDITION IS THAT 5e MUST NOT REACH A PRODUCTION TENANT UNTIL THAT EXISTS. A condition
    recorded only in a report is a condition nobody will find; a docstring goes stale silently.
    This is the third thing: it fails if the paragraph is deleted, which is the edit that would
    otherwise quietly turn a temporary decision into a permanent one.
    """
    source = Path(cm_permissions.__file__).read_text(encoding="utf-8")
    for required in (
        "KNOWN-BROADER",
        "must not reach a production tenant",
        "SYNAPSE",
        "PROVISION",
    ):
        assert required in source, (
            f"the known-broader condition no longer names {required!r}. If the CM permission was "
            "replaced with a Synapse-specific one, update this test in the same commit; if the "
            "paragraph was merely tidied away, put it back"
        )


def test_the_gate_is_layered_on_require_platform_not_instead_of_it() -> None:
    """A TENANT TOKEN MUST BE REFUSED BEFORE ANY OUTBOUND CALL IS MADE.

    Two reasons and both are real: a token that could never pass should not cost a request to
    another service, and `user_type` staying the single answer to "is this an operator" is the
    ledger item auth.py refuses to inherit. The permission answers a different question and joins
    nothing.

    READ OFF THE ANNOTATION, not the default. This service declares dependencies as
    ``Annotated[Identity, Depends(require_platform)]``, which is FastAPI's current idiom and puts
    the Depends marker in the annotation's metadata rather than in the parameter's default. A test
    that looked at defaults would find nothing and pass vacuously against a route with no gate at
    all, which is the failure mode this whole file is about.
    """
    import inspect
    from typing import get_args, get_origin

    from synapse_ui_server.auth import require_platform

    hints = inspect.get_annotations(cm_permissions.require_tenant_configure, eval_str=True)
    markers = [
        meta
        for annotation in hints.values()
        if get_origin(annotation) is not None
        for meta in get_args(annotation)[1:]
        if hasattr(meta, "dependency")
    ]
    assert markers, "no Depends marker found at all; this test has stopped biting"
    assert any(marker.dependency is require_platform for marker in markers), (
        "require_tenant_configure no longer depends on require_platform"
    )
