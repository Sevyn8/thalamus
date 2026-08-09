"""Which timezone names this console may offer: the ones BOTH databases accept.

=================================================================================================
THE DEFECT THIS MODULE EXISTS TO MAKE IMPOSSIBLE
=================================================================================================
Slice 5e populated the timezone picker from the BROWSER, with
``Intl.supportedValuesOf("timeZone")``. On staging the picker offered ``Asia/Calcutta`` and
``Asia/Katmandu``, did not offer ``Asia/Kolkata`` AT ALL, and every enable was refused with a 422
before the INSERT. Every tenant in production is ``Asia/Kolkata``, so the control could not emit
the only value anybody needed. Nothing could be provisioned.

WHY THE BROWSER OFFERS THOSE NAMES AND NOT THE RIGHT ONE. ECMA-402 resolves zone identifiers
through CLDR/ICU, which historically treats ``Asia/Calcutta`` as the CANONICAL name and
``Asia/Kolkata`` as the alias. IANA says the opposite. So the browser's list is not wrong, it is
answering a different question, and no amount of care on the browser side would have fixed it.

THE FIX IS STRUCTURAL RATHER THAN CAREFUL. The offered list is the INTERSECTION of the two
databases that can refuse a value: this service's Python ``zoneinfo`` and the Postgres instance
the row lands in. An intersection cannot contain a name either side rejects, so "offered" and
"writable" become the same set by construction. The previous design tried to hold that property
by review, and review is what failed.

=================================================================================================
THIS DEFECT DOES NOT REPRODUCE ON A DEVBOX. MEASURED, NOT ASSUMED.
=================================================================================================
Anyone testing zone handling locally is testing a DIFFERENT TIMEZONE DATABASE from the one that
ships, and the local one is more permissive, so the local result is the reassuring one.

    python:3.12-slim  (the deployed base image)     available_timezones() -> 486 names
      Asia/Kolkata    present
      Asia/Calcutta   ZoneInfoNotFoundError
      Asia/Katmandu   ZoneInfoNotFoundError

    dis/.venv on a devbox (system tzdata + the       available_timezones() -> 599 names
    tzdata PyPI package)
      Asia/Kolkata    present
      Asia/Calcutta   present and RESOLVES
      Asia/Katmandu   present and RESOLVES

WHY THEY DIFFER: Debian's slim ``tzdata`` ships the canonical IANA zones and OMITS the
backward-compatibility links. The ``tzdata`` PyPI package, which carries them, is NOT in this
service's dependency closure (checked with ``uv tree --package synapse-ui-server``), so the
container has exactly Debian's canonical set and nothing else. A devbox that has both gets the
union.

THE CONSEQUENCE, WHICH IS THE PART WORTH REMEMBERING: ``ZoneInfo("Asia/Calcutta")`` SUCCEEDS on a
devbox and RAISES in the container. A fix verified locally would have looked correct and shipped
the same failure. Same shape as this project's standing rule about reproducing RLS behaviour
under a superuser: the local environment answered a question the deployed one was not being
asked.

POSTGRES VARIES THE SAME WAY AND IN THE SAME DIRECTION. Stock ``postgres:16`` returns 487 names
and contains NEITHER ``Asia/Calcutta`` NOR ``Asia/Katmandu``, because it is built against that
same Debian tzdata. Cloud SQL, measured on staging by the operator, DOES carry both, because it
is built against a full tzdata including backward links. Both shapes were checked and the design
survives both, because Python's set is the binding constraint either way:

    intersection with Cloud SQL (~1190 names)  ->  about 486, Kolkata in, Calcutta out
    intersection with postgres:16 (487 names)  ->  486 exactly, Kolkata in, Calcutta out
      (measured: python - postgres = {}, postgres - python = {'posixrules'})

=================================================================================================
NO SILENT TRANSLATION, EVER
=================================================================================================
It is tempting to map ``Asia/Calcutta`` to ``Asia/Kolkata`` and move on, since they are the same
zone with identical offsets. This module does not, and will not.

``synapse.provision.timezone`` is IMMUTABLE. It feeds every action's ``as_of``, which sits inside
an append-only idempotency index that cannot be re-keyed. Silently rewriting an operator's input
on the way into a column nobody can ever correct means the stored value is one nobody typed and
nobody was shown. A name not in the intersection is not offered and is refused with an
explanation. Refusing is recoverable; a silent rewrite is not.

=================================================================================================
THE STARTUP READ, AND WHY IT MUST NOT BE ABLE TO KILL THE SERVICE
=================================================================================================
Computing the intersection means asking Postgres, which makes STARTUP touch the database. That is
a new failure mode on a path that had none, so it is bounded here rather than left to Cloud Run:
``load_offered`` catches everything and falls back to Python's set alone.

A BROKEN PICKER BEATS A DEAD CONSOLE. The console is five read screens and one write; a database
that cannot answer this one query would take all six down for the sake of one.

READINESS IS DELIBERATELY NOT COUPLED TO THIS. ``/readyz`` keeps its own independent session, so a
database that is genuinely down still fails readiness through the path that exists to detect it,
rather than through this one.

THE FALLBACK IS A REAL WEAKENING AND IS REPORTED AS ONE. Python's set alone can contain a name
Postgres rejects, which is the dead-control class in the opposite direction: offerable, and
refused by the trigger AFTER the operator has committed. It is much narrower than the failure
being fixed (Debian's canonical set was an exact subset of the 487 measured above), but it is not
nothing, so ``OfferedZones.source`` carries which path was taken, the endpoint serves it, and the
console says so plainly instead of looking healthy.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass
from typing import Literal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_core.logging import get_logger
from dis_rls import rls_platform_session

__all__ = ["OfferedZones", "load_offered", "python_zones"]

_log = get_logger("synapse-ui-server")

# EVERY NAME POSTGRES WILL ACCEPT, asked of the instance the row actually lands in.
#
# NOT A HARDCODED LIST AND NOT A VERSION CHECK. Which names a Postgres accepts is a property of
# the tzdata it was BUILT against, which differs between the stock docker image and Cloud SQL by
# roughly seven hundred names. Asking is the only way to know, and asking at startup means the
# answer tracks a database upgrade without a release.
#
# NO GRANT IS NEEDED: pg_timezone_names is a catalog view readable by PUBLIC, and it carries no
# RLS, so there is no silent-zero trap here. The session helper is used anyway, because it also
# runs dis-rls's first-use target and role guard.
_PG_ZONES = text("SELECT name FROM pg_timezone_names")


def python_zones() -> frozenset[str]:
    """What THIS PROCESS can resolve. See the module header for why this is 486 and not 599."""
    return frozenset(zoneinfo.available_timezones())


@dataclass(frozen=True)
class OfferedZones:
    """The zones the console may offer, and how the answer was arrived at.

    ``source`` IS PART OF THE PAYLOAD, not a diagnostic. ``intersection`` means offered and
    writable are the same set. ``python_only`` means the Postgres half could not be read and a
    name here might still be refused by the trigger, which the console has to be able to say.
    """

    names: tuple[str, ...]
    source: Literal["intersection", "python_only"]
    python_count: int
    # None in the degraded path, which is the honest value: not zero, because zero would read as
    # "Postgres knows no timezones" rather than "Postgres was not asked".
    postgres_count: int | None

    def offers(self, name: str) -> bool:
        """Membership, which is the question the enable route asks.

        A SET WOULD BE FASTER AND ``names`` IS A TUPLE ON PURPOSE: this object is frozen and
        serialised in list order, and keeping ONE representation means the thing checked is the
        thing served. Roughly 486 entries is not a hot path.
        """
        return name in self.names


async def load_offered(engine: AsyncEngine) -> OfferedZones:
    """The intersection, or Python's set alone. NEVER RAISES.

    Every failure is the same answer: a degraded list, a WARNING naming what happened, and a
    service that starts. Connection refused, a timeout, dis-rls refusing the target database or a
    bypassing role, a permission error on the catalog view: all of them mean Postgres could not be
    asked, and none of them is a reason to take a read-only console down.

    THE BARE ``except Exception`` IS DELIBERATE AND IS THE POINT OF THE FUNCTION. A narrower catch
    would be a list of the failures somebody thought of, and the one that matters is the one
    nobody did. This is the only place in the service where that is the right shape, because it
    is the only place whose contract is "produce an answer, never a failure".
    """
    available = python_zones()

    try:
        async with rls_platform_session(engine, None) as conn:
            rows = (await conn.execute(_PG_ZONES)).scalars().all()
    except Exception as exc:
        _log.warning(
            "timezone list DEGRADED: Postgres could not be asked, offering Python's set alone. "
            "A zone offered from this list may still be refused by synapse.provision's trigger",
            extra={
                "severity": "WARNING",
                "event": "synapse.timezones.degraded",
                "source": "python_only",
                "python_count": len(available),
                "error": type(exc).__name__,
            },
        )
        return OfferedZones(
            names=tuple(sorted(available)),
            source="python_only",
            python_count=len(available),
            postgres_count=None,
        )

    postgres = frozenset(rows)
    offered = tuple(sorted(available & postgres))
    _log.info(
        "timezone list computed as the intersection of this service and this database",
        extra={
            "severity": "NOTICE",
            "event": "synapse.timezones.loaded",
            "source": "intersection",
            "python_count": len(available),
            "postgres_count": len(postgres),
            "offered_count": len(offered),
        },
    )
    return OfferedZones(
        names=offered,
        source="intersection",
        python_count=len(available),
        postgres_count=len(postgres),
    )
