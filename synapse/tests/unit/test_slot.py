"""The slot function: the one piece of orchestration kept free of Synapse types.

WHAT THESE PIN, and each is a way a slot silently stops being stable:

  - the floor is TENANT-LOCAL, so an IST tenant's day is not a UTC day
  - a retry minutes later floors to the SAME slot, which is the whole reason the function exists
  - a naive instant is REFUSED rather than assumed to be UTC
  - an unresolvable timezone is REFUSED rather than defaulted

No test here reimplements the flooring. Asserting ``slot_for(...) == instant.astimezone(zone).date()``
would be the same arithmetic twice and would pass with both copies wrong; every assertion below
is a literal date a human worked out from the offset.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from synapse.core.slot import Cadence, slot_for

IST = "Asia/Kolkata"


# ---------------------------------------------------------------------------
# Tenant-local, not UTC
# ---------------------------------------------------------------------------


def test_an_ist_morning_before_0530_is_the_same_local_day_not_the_previous_utc_one() -> None:
    """THE RECORDED FINDING, one layer up. Canonical already has a UTC-boundary problem: an IST
    sale before 05:30 local falls on the PREVIOUS UTC date. If the slot were computed in UTC, a
    run dispatched at 09:00 IST would stamp its actions with yesterday.

    03:00 IST on the 5th is 21:30 UTC on the 4th. The slot must be the 5th.
    """
    instant = datetime(2026, 8, 4, 21, 30, tzinfo=UTC)
    assert instant.astimezone(ZoneInfo(IST)).hour == 3, "the fixture must actually straddle"
    assert slot_for(Cadence.DAILY, IST, instant) == date(2026, 8, 5)


def test_the_same_instant_gives_different_slots_in_different_zones() -> None:
    """Two tenants, one dispatch, two legitimately different days. This is what the per-tenant
    timezone column buys, and it is why the slot cannot be computed once for the sweep."""
    instant = datetime(2026, 8, 4, 21, 30, tzinfo=UTC)
    assert slot_for(Cadence.DAILY, IST, instant) == date(2026, 8, 5)
    assert slot_for(Cadence.DAILY, "UTC", instant) == date(2026, 8, 4)
    assert slot_for(Cadence.DAILY, "America/New_York", instant) == date(2026, 8, 4)


def test_a_utc_instant_late_in_the_day_is_still_the_next_day_in_sydney() -> None:
    instant = datetime(2026, 8, 4, 20, 0, tzinfo=UTC)
    assert slot_for(Cadence.DAILY, "Australia/Sydney", instant) == date(2026, 8, 5)


# ---------------------------------------------------------------------------
# Stability under retry — the reason the function exists
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("minutes", [1, 5, 30, 120])
def test_a_retry_later_the_same_local_day_floors_to_the_same_slot(minutes: int) -> None:
    """Cloud Scheduler retries its own API call, so a second execution can be launched whatever
    the job's max_retries says. Every one of those must land on the same slot or the run key
    stops identifying a run."""
    first = datetime(2026, 8, 4, 3, 30, tzinfo=UTC)
    later = first + timedelta(minutes=minutes)
    assert slot_for(Cadence.DAILY, IST, first) == slot_for(Cadence.DAILY, IST, later)


def test_the_residual_is_real_a_retry_across_local_midnight_is_a_different_slot() -> None:
    """THE LIMITATION, PINNED RATHER THAN HIDDEN. The module docstring says a dispatch straddling
    local midnight produces two slots. If that ever silently stopped being true the docstring
    would be wrong, and a test asserting the honest limitation is how it stays honest.

    23:58 and 00:02 IST, four minutes apart, two days.
    """
    before = datetime(2026, 8, 4, 18, 28, tzinfo=UTC)  # 23:58 IST on the 4th
    after = datetime(2026, 8, 4, 18, 32, tzinfo=UTC)  # 00:02 IST on the 5th
    assert slot_for(Cadence.DAILY, IST, before) == date(2026, 8, 4)
    assert slot_for(Cadence.DAILY, IST, after) == date(2026, 8, 5)


def test_a_dst_transition_does_not_split_a_day() -> None:
    """A zone that actually observes DST, on a day it changes. The local date is still one date;
    flooring must not fall out of the 23- or 25-hour day."""
    # 2026-03-29 is the European spring-forward. 00:30 and 23:30 London on that date.
    early = datetime(2026, 3, 29, 0, 30, tzinfo=ZoneInfo("Europe/London"))
    late = datetime(2026, 3, 29, 23, 30, tzinfo=ZoneInfo("Europe/London"))
    assert slot_for(Cadence.DAILY, "Europe/London", early) == date(2026, 3, 29)
    assert slot_for(Cadence.DAILY, "Europe/London", late) == date(2026, 3, 29)


# ---------------------------------------------------------------------------
# The refusals
# ---------------------------------------------------------------------------


def test_a_naive_instant_is_refused() -> None:
    """Guessing UTC is invisible when right and shifts every slot by the offset when wrong."""
    with pytest.raises(ValueError, match="timezone-aware"):
        slot_for(Cadence.DAILY, IST, datetime(2026, 8, 4, 21, 30))


def test_an_unresolvable_timezone_is_refused() -> None:
    """A bad zone does not fail a run; it mis-stamps every as_of. It must fail here."""
    with pytest.raises(ValueError, match="IANA"):
        slot_for(Cadence.DAILY, "Mars/Olympus_Mons", datetime(2026, 8, 4, 21, 30, tzinfo=UTC))


def test_an_empty_timezone_is_refused() -> None:
    with pytest.raises(ValueError, match="IANA"):
        slot_for(Cadence.DAILY, "", datetime(2026, 8, 4, 21, 30, tzinfo=UTC))


def test_a_fixed_offset_instant_is_accepted_without_being_reinterpreted() -> None:
    """The caller may supply any aware instant, not only UTC. 09:00+05:30 IS 03:30 UTC, which is
    09:00 IST, so the slot is that day."""
    instant = datetime.fromisoformat("2026-08-05T09:00:00+05:30")
    assert slot_for(Cadence.DAILY, IST, instant) == date(2026, 8, 5)
