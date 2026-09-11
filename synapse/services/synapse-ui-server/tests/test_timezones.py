"""The offered timezone set: the intersection, the fallback, and the names that broke staging.

THE FAILURE THESE PIN. The picker was once populated from the browser, which offered
``Asia/Calcutta`` and ``Asia/Katmandu`` and did NOT offer ``Asia/Kolkata`` at all. Every tenant in
production is Asia/Kolkata, so the control could not emit the only value anybody needed, and every
attempt was refused with a 422 before the INSERT. Nothing could be provisioned.

READ timezones.py's HEADER BEFORE CHANGING ANYTHING HERE. The short version: the deployed base
image carries Debian's canonical tzdata (486 names, no backward links) and a devbox carries the
union with the tzdata package (599, with them), so ``ZoneInfo("Asia/Calcutta")`` RAISES in the
container and SUCCEEDS locally. The defect does not reproduce on a devbox.

WHICH IS WHY THE TESTS BELOW DO NOT ASSERT THAT ASIA/CALCUTTA IS ABSENT FROM PYTHON'S SET. That
assertion would pass in CI-on-a-container and fail on the machine of whoever next runs `make test`
locally, and the natural response to a red test that passes elsewhere is to delete it. The
property that actually matters is INDEPENDENT of which tzdata is installed and is what is asserted
instead: whatever either side rejects is not offered.
"""

from __future__ import annotations

import zoneinfo
from typing import Any

import pytest
from synapse_ui_server import timezones as timezones_module
from synapse_ui_server.timezones import OfferedZones, load_offered, python_zones


class _FakeResult:
    def __init__(self, names: list[str]) -> None:
        self._names = names

    def scalars(self) -> _FakeResult:
        return self

    def all(self) -> list[str]:
        return self._names


class _RecordingConn:
    def __init__(self, names: list[str]) -> None:
        self.calls: list[str] = []
        self._names = names

    async def execute(self, statement: object, params: Any = None) -> _FakeResult:
        self.calls.append(str(statement))
        return _FakeResult(self._names)


@pytest.fixture
def patched(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Swap rls_platform_session AT THE MODULE, so timezones.py's own call site is under test.

    Also the shape that lets a test make the session RAISE, which is the whole point of the
    fallback and cannot be exercised any other way without a broken database.
    """

    def install(*, names: list[str] | None = None, raises: Exception | None = None) -> _RecordingConn:
        conn = _RecordingConn(names or [])

        from contextlib import asynccontextmanager

        @asynccontextmanager
        async def fake(engine: object, tenant: object = None):  # type: ignore[no-untyped-def]
            if raises is not None:
                raise raises
            yield conn

        monkeypatch.setattr(timezones_module, "rls_platform_session", fake)
        return conn

    return install


# ---------------------------------------------------------------------------
# THE INTERSECTION
# ---------------------------------------------------------------------------


async def test_a_name_only_postgres_knows_is_not_offered(patched) -> None:  # type: ignore[no-untyped-def]
    """THE STAGING FAILURE, ASSERTED WITHOUT DEPENDING ON THE LOCAL TZDATA.

    Asia/Calcutta is the real case: Cloud SQL carries it, and the deployed image's Python does
    not. Rather than asserting Python's set (which differs between the container and a devbox),
    this hands Postgres a name that CANNOT be in any Python set and checks it is dropped. The
    property is the same one and it holds everywhere.
    """
    patched(names=[*sorted(python_zones()), "Mars/Olympus_Mons"])

    offered = await load_offered(object())  # type: ignore[arg-type]

    assert offered.source == "intersection"
    assert "Mars/Olympus_Mons" not in offered.names, (
        "a name only Postgres knows was offered. Python would refuse it at _validate and the "
        "control would be dead after the operator committed"
    )


async def test_a_name_only_python_knows_is_not_offered(patched) -> None:  # type: ignore[no-untyped-def]
    """THE OTHER DIRECTION, and it is the one the intersection exists for rather than the one
    that broke: a zone this process resolves and the database refuses would pass _validate, reach
    the INSERT, and be refused by the trigger AFTER the operator committed."""
    real = sorted(python_zones())
    assert len(real) > 2
    withheld = real[0]
    patched(names=real[1:])

    offered = await load_offered(object())  # type: ignore[arg-type]

    assert withheld not in offered.names
    assert real[1] in offered.names


async def test_kolkata_is_offered_when_both_sides_have_it(patched) -> None:  # type: ignore[no-untyped-def]
    """THE BASELINE, AND THE ONE THAT WOULD HAVE UNBLOCKED STAGING. Every tenant in production is
    Asia/Kolkata; a fix that removed Calcutta and did not offer Kolkata would have moved the
    control from wrong to empty."""
    assert "Asia/Kolkata" in python_zones(), (
        "this Python has no Asia/Kolkata at all, which no supported base image should produce"
    )
    patched(names=["Asia/Kolkata", "Asia/Calcutta", "Etc/UTC"])

    offered = await load_offered(object())  # type: ignore[arg-type]

    assert "Asia/Kolkata" in offered.names
    assert offered.offers("Asia/Kolkata")


async def test_a_deprecated_alias_is_dropped_whenever_this_python_lacks_it(patched) -> None:  # type: ignore[no-untyped-def]
    """THE NAMED CASE, asserted conditionally rather than skipped or faked.

    On the deployed base image Python lacks Asia/Calcutta and this asserts the real thing. On a
    devbox with the tzdata package Python HAS it, both sides agree, and offering it is correct,
    so the test asserts the agreement instead. Either way it fails if the intersection stops
    being an intersection, and neither branch is a lie about the other environment.
    """
    both = ["Asia/Kolkata", "Asia/Calcutta"]
    patched(names=both)

    offered = await load_offered(object())  # type: ignore[arg-type]

    if "Asia/Calcutta" in python_zones():
        assert "Asia/Calcutta" in offered.names, (
            "this Python resolves Asia/Calcutta and Postgres offered it, so dropping it would be "
            "the intersection doing something other than intersecting"
        )
    else:
        assert "Asia/Calcutta" not in offered.names, (
            "this Python cannot resolve Asia/Calcutta, so offering it is the staging defect: the "
            "picker would show a name _validate refuses"
        )
    assert "Asia/Kolkata" in offered.names


async def test_the_offered_names_are_sorted_and_unique(patched) -> None:  # type: ignore[no-untyped-def]
    """Rendered directly into a select in this order, and grouped by prefix on the way. Duplicates
    would produce two identical options; unsorted would scatter a region across the list."""
    patched(names=["Etc/UTC", "Asia/Kolkata", "Etc/UTC", "Africa/Djibouti"])

    offered = await load_offered(object())  # type: ignore[arg-type]

    assert list(offered.names) == sorted(set(offered.names))


async def test_the_query_asks_postgres_and_nothing_else(patched) -> None:  # type: ignore[no-untyped-def]
    """PINNED ON THE STATEMENT. pg_timezone_names is the only thing that can answer what THIS
    database accepts; a hardcoded list or a version check would be a guess about a build option.
    """
    conn = patched(names=["Asia/Kolkata"])

    await load_offered(object())  # type: ignore[arg-type]

    assert len(conn.calls) == 1
    assert "pg_timezone_names" in conn.calls[0]


# ---------------------------------------------------------------------------
# THE FALLBACK. A broken picker beats a dead console.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "failure",
    [
        OSError("connection refused"),
        TimeoutError("no answer"),
        RuntimeError("dis-rls refused the target database"),
        Exception("something nobody thought of"),
    ],
)
async def test_any_startup_failure_falls_back_instead_of_raising(patched, failure: Exception) -> None:  # type: ignore[no-untyped-def]
    """NEVER RAISES, AND THE LAST CASE IS THE POINT.

    A narrower catch would be a list of the failures somebody thought of. The one that matters is
    the one nobody did, so the bare Exception is asserted deliberately rather than tolerated: this
    function's contract is "produce an answer", and a startup that dies here would take five
    working read screens down for the sake of one dropdown.
    """
    patched(raises=failure)

    offered = await load_offered(object())  # type: ignore[arg-type]

    assert offered.source == "python_only"
    assert offered.names, "the fallback produced an empty list, which is a dead control"
    assert offered.offers("Asia/Kolkata")


async def test_the_fallback_reports_postgres_as_unasked_not_as_empty(patched) -> None:  # type: ignore[no-untyped-def]
    """None, NOT ZERO. A zero would read as "Postgres knows no timezones", which is a claim about
    the database rather than about what happened, and it is the kind of number that ends up in an
    incident summary as a fact."""
    patched(raises=OSError("down"))

    offered = await load_offered(object())  # type: ignore[arg-type]

    assert offered.postgres_count is None
    assert offered.python_count == len(python_zones())


async def test_the_degraded_path_logs_at_warning_naming_which_path(patched, caplog) -> None:  # type: ignore[no-untyped-def]
    """LOUD, AND MACHINE-MATCHABLE. dis_core's logger emits `severity`; Cloud Logging files
    anything without it at DEFAULT, where no alert can match. The `source` field is what
    distinguishes a degraded start from a healthy one in a log nobody is watching at the time."""
    import logging

    patched(raises=OSError("down"))
    with caplog.at_level(logging.WARNING):
        await load_offered(object())  # type: ignore[arg-type]

    assert any(
        record.levelno == logging.WARNING and getattr(record, "source", None) == "python_only"
        for record in caplog.records
    ), "the degraded startup path did not log a WARNING naming source=python_only"


async def test_the_healthy_path_logs_both_counts(patched, caplog) -> None:  # type: ignore[no-untyped-def]
    """THE BASELINE FOR THE TEST ABOVE, and the numbers are worth having: the two counts in one
    line are what let somebody see that a base-image change moved Python's set."""
    import logging

    patched(names=["Asia/Kolkata", "Etc/UTC"])
    with caplog.at_level(logging.INFO):
        await load_offered(object())  # type: ignore[arg-type]

    matched = [r for r in caplog.records if getattr(r, "source", None) == "intersection"]
    assert matched, "the healthy startup path logged no line naming source=intersection"
    assert getattr(matched[0], "postgres_count", None) == 2
    assert getattr(matched[0], "python_count", 0) > 0


# ---------------------------------------------------------------------------
# THE MEMBERSHIP TEST THE ROUTE USES
# ---------------------------------------------------------------------------


def test_offers_answers_on_the_served_list_not_on_python() -> None:
    """THE ROUTE'S QUESTION, and it must be about the SERVED set. Answering from
    available_timezones() would let a name through that the console never offered, which is the
    gap the intersection closes."""
    offered = OfferedZones(names=("Asia/Kolkata",), source="intersection", python_count=1, postgres_count=1)
    assert offered.offers("Asia/Kolkata")
    assert not offered.offers("Etc/UTC")
    assert "Etc/UTC" in zoneinfo.available_timezones(), (
        "the negative case above is vacuous unless Etc/UTC is a zone Python really does resolve"
    )


def test_python_zones_is_read_from_zoneinfo_rather_than_listed() -> None:
    """A VACUITY GUARD. Every intersection test above is over this set; a helper that returned an
    empty set would make them all pass while offering nothing."""
    zones = python_zones()
    assert len(zones) > 100, f"only {len(zones)} zones resolved; this Python has no tzdata"
    assert "Asia/Kolkata" in zones
