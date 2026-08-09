"""The SECOND write path in this service. One INSERT, one table, one credential (slice 5e).

THIS MODULE IS A PORT, NOT A NEW PROCEDURE. ``infra/db-setup/sql/provision_analysis.sql`` is the
procedure an operator has run by hand until now, and its value is almost entirely in the two
pre-flight checks and the two hardcoded columns. A form discards all four by default: it asks for
a tenant, an analysis and a timezone, and quietly drops everything the file spent a hundred lines
arguing for. So each one has a deliberate home here, and this docstring says which.

A SEPARATE MODULE FROM ``lifecycle.py`` rather than a second function in it, for the same reason
lifecycle.py is separate from reads.py: "where can this service write" must keep a one-file-per-
credential answer, and the no-write test names the exceptions individually rather than being
weakened into a general permission. Two write modules, two roles, two tables, and the test counts
them.

=================================================================================================
THE FOUR PROPERTIES THE CONSOLE MUST NOT LOSE, AND WHERE EACH ONE LIVES
=================================================================================================

1. THE PRE-FLIGHT IS THE POINT, AND IT IS IN THE SAME TRANSACTION AS THE INSERT.

   An unknown tenant UUID inserts fine, enumerates fine, and produces a healthy run with zero
   actions every day for ever. NOTHING GOES RED. That is the failure this exists to prevent and
   it is invisible by construction, which is why it is enforced here rather than trusted to a
   caller. Both branches survive the port and they stay DIFFERENT:

     tenant not in identity_mirror  -> FATAL. Raises, the transaction rolls back, nothing is
                                       provisioned.
     tenant exists, zero positions  -> WARNS and PROCEEDS. Enabling ahead of ingestion is a real
                                       thing to want; a silent zero is not.

   THE STRONGER MITIGATION IS UPSTREAM AND IS NOT IN THIS FILE. The console offers no UUID text
   field: the tenant comes from the fleet list, so the operator picks a row rather than typing
   an identifier. Removing the failure beats catching it. This check is what remains for the
   cases a picker cannot cover, which are a stale page and a hand-made request.

2. cadence AND rung ARE CONSTANTS IN THIS FILE. Not parameters, not form fields, not columns of
   any request model. See ``CADENCE`` and ``RUNG`` below for the blast-radius argument.

3. THE TIMEZONE IS CHOSEN ONCE AND IS NEVER EDITED. Selectable at enable; there is no code path
   here that can change one afterwards, and the grant has no UPDATE so there is no code path that
   could be added without a grant change. It feeds every action's ``as_of``, which sits inside an
   append-only idempotency index that cannot be re-keyed, so a revision would silently re-date a
   customer's analytics history rather than fail.

4. THERE IS NO DISABLE AND NO RE-ENABLE, and their absence is enforced three deep: no function
   here, no UPDATE in the grant, and a three-state read on the console so a disabled pair renders
   as disabled rather than as available. ``synapse.provision`` holds ONE window per
   (tenant, analysis), so clearing ``disabled_at`` LOSES THE FACT THAT THERE WAS A GAP and the
   attribution denominator for that period silently becomes wrong. provision.sql names the fix
   (an append-only enablement history) and names its trigger: THE FIRST DISABLE.

=================================================================================================
THE FIFTH PROPERTY, WHICH THE PROCEDURE DID NOT NEED AND AN ENDPOINT DOES
=================================================================================================
AN UNKNOWN ``analysis_id`` REFUSES THE WHOLE SWEEP FOR EVERY TENANT. ``check_envelope`` in
synapse/persistence/provision_postgres.py raises ``ProvisionRefusedError`` (the CORE one, a
different class from this module's ``EnablementRefusedError``) when any provisioned
analysis id is absent from the declarations, and the orchestrator loads the table as one list, so
the refusal takes the ENTIRE ENUMERATION rather than one row. Identical blast radius to a wrong
rung, and the DDL cannot help: ``ck_provision_analysis_named`` only checks ``length > 0``.

The hand-run file never needed this because a human typing ``dead_stcok`` would see the dry run
fail the same day. An endpoint would accept it, return 201, and stop the fleet's sweep at 04:00.
So the id is checked against ``declared_analysis_ids()`` here, and the console offers a LIST
rather than a text field, for exactly the reason the tenant does.

=================================================================================================
WHAT KEEPS IT NARROW, AND ONLY THE LAST IS CODE
=================================================================================================
  1. THE CREDENTIAL. ``synapse_provisioner`` holds INSERT on ``synapse.provision`` plus SELECT on
     the two tables the pre-flight reads, and nothing else. No UPDATE, no DELETE, no SELECT on
     provision itself. This module could contain any statement and Postgres would refuse it.
  2. THE POLICY. FORCE ROW LEVEL SECURITY with ``WITH CHECK (tenant_id = app.tenant_id)``, so the
     write opens a TENANT-scoped session for the tenant being enabled. A PLATFORM session (tenant
     GUC '') can read every provision and write none, which is why the read path and the write
     path cannot share one session helper. The same shape as lifecycle.py, forced by the same
     clause.
  3. THE TRIGGER. ``trg_provision_timezone_resolves`` refuses an unresolvable zone for every role
     including the owner. Its message is SURFACED, never swallowed: a zone that does not resolve
     shifts every slot silently instead of failing, so the operator has to see it.
  4. THE VOCABULARY. Cadence and rung are constants and the analysis id is checked against the
     registry, so a bad value is refused at the boundary with a message naming the legal set.

THE ROLE CANNOT SEE WHETHER ITS OWN INSERT WAS SUPPRESSED, and that is correct rather than a gap.
``ON CONFLICT DO NOTHING`` needs no SELECT privilege; ``RETURNING`` would, and granting SELECT to
find out would let the enablement credential read every customer's configuration back. The
console answers "what is true now" through ``synapse_reader``, before and after, which is the same
division 5d uses for the alert it is about to act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final
from uuid import UUID
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_rls import rls_session
from synapse.registry import declared_analysis_ids

__all__ = [
    "CADENCE",
    "RUNG",
    "EnableOutcome",
    "EnablementRefusedError",
    "enable_analysis",
]


# =================================================================================================
# cadence AND rung: CONSTANTS, AND THIS IS A SAFETY PROPERTY RATHER THAN A SIMPLIFICATION
# =================================================================================================
# NEITHER IS A PARAMETER OF ANY FUNCTION HERE, A FIELD OF ANY REQUEST MODEL, OR A COLUMN OF ANY
# FORM. That is the whole mechanism: a value that cannot be typed cannot be mistyped.
#
# WHY rung IS THE DANGEROUS ONE. The envelope check (a provision may not exceed its analysis's
# declared max_rung) runs when the ORCHESTRATOR LOADS THE TABLE, in
# synapse/persistence/provision_postgres.py::check_envelope, and it refuses the WHOLE ENUMERATION
# rather than one row. So ONE wrong rung on ONE tenant stops the 04:00 sweep for EVERY tenant, and
# the tenant it stops is not the one that was edited.
#
# AND A NAIVE DROPDOWN WOULD OFFER THE FLEET-BREAKING VALUE. The DDL's ck_provision_rung permits
# ('shadow', 'suggest') because Rung declares both, and a form built by reading the CHECK
# constraint would render two options. NOTHING IMPLEMENTS 'suggest': there is no delivery of any
# kind, and synapse.core.provision.Rung says so at length. Picking it from a dropdown would be a
# one-click fleet outage that passes every constraint in the database.
#
# cadence is hardcoded for the smaller version of the same reason: 'daily' is the only member of
# the enum, so a variable could only ever be wrong.
#
# WHEN A SECOND RUNG OR CADENCE GENUINELY EXISTS, they become parameters here and the endpoint
# grows a validated field. Not before, and not because a form looked incomplete.
CADENCE: Final[str] = "daily"
RUNG: Final[str] = "shadow"


class EnablementRefusedError(ValueError):
    """An enablement this module refuses to perform.

    ``reason`` is machine-stable so the route can choose a status code without parsing prose. The
    message is for the operator and is the only thing they can act on, which is why the trigger's
    own text is passed through verbatim rather than replaced with something tidier.
    """

    def __init__(self, message: str, *, reason: str) -> None:
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class EnableOutcome:
    """What became true, reported so the enable is not a silent success.

    ``warning`` carries the zero-positions case. It is not an error and must not be rendered as
    one: enabling ahead of ingestion is legitimate, and the reason to say it out loud is that a
    monitor producing nothing for a week is otherwise indistinguishable from a monitor that is
    working and finding nothing.

    THERE IS NO ``created`` FLAG, and its absence is the grant showing through. The credential
    holds no SELECT on synapse.provision, so this module genuinely cannot tell an insert from a
    suppressed one. Inventing the field would mean asserting something unmeasured, which is the
    class of defect this console has a standing rule against. The route establishes the three
    enablement states through synapse_reader BEFORE calling here, and re-reads afterwards.
    """

    analysis_id: str
    tenant_name: str
    canonical_positions: int
    warning: str | None


# -------------------------------------------------------------------------------------------------
# The three statements. Written out rather than built, so a reader of this file sees the entire
# database surface of the second write path at once.
#
# TWO OF THEM ARE THE PRE-FLIGHT AND THEY ARE NOT OPTIONAL. They are the reason the credential
# needed two SELECTs at all (see 05_synapse_provisioner_grant.sql), and they run on the SAME
# CONNECTION as the insert below, inside the one transaction rls_session opens.
# -------------------------------------------------------------------------------------------------

# FATAL BRANCH. identity_mirror has no RLS, so a missing grant here is a loud permission error
# rather than a silent zero, and a genuinely absent tenant is the only way this returns nothing.
_TENANT_NAME = text(
    """
    SELECT name
      FROM identity_mirror.tenants
     WHERE tenant_id = CAST(:tenant_id AS uuid)
    """
)

# WARN BRANCH. This table IS FORCE ROW LEVEL SECURITY, so the count is only meaningful inside the
# tenant-scoped session opened below. Under the wrong GUCs it returns 0 and raises nothing, and
# the endpoint would then warn "no canonical positions" about a tenant with thousands.
_POSITION_COUNT = text(
    """
    SELECT count(*)
      FROM canonical.store_sku_current_position
     WHERE tenant_id = CAST(:tenant_id AS uuid)
    """
)

# THE WRITE. cadence and rung are bound from the module constants above rather than interpolated,
# so the parameter list of this statement is the same shape as every other and a future reader
# cannot mistake them for caller input.
#
# ON CONFLICT DO NOTHING makes re-enabling idempotent and, critically, makes it a NO-OP against a
# pair that was deliberately DISABLED: re-running never resurrects one. That is the same guarantee
# provision_analysis.sql gives, and it is why the console must establish the three states through
# the reader instead of treating a 201 as evidence.
_ENABLE = text(
    """
    INSERT INTO synapse.provision (
        tenant_id, analysis_id, cadence, rung, timezone, enabled_at
    ) VALUES (
        CAST(:tenant_id AS uuid), :analysis_id, :cadence, :rung, :timezone, :enabled_at
    )
    ON CONFLICT ON CONSTRAINT pk_provision DO NOTHING
    """
)


def _validate(analysis_id: str, timezone: str) -> None:
    """Refuse a bad request BEFORE any connection is opened. Both checks have a second enforcer.

    THE ANALYSIS ID, against the registry. An id the declarations do not know refuses the whole
    enumeration at 04:00 for every tenant (see the module docstring). Nothing in the database can
    catch this: the CHECK constraint only requires a non-empty string, and the table cannot see a
    Python declaration.

    THE TIMEZONE, against ZoneInfo, AND THE MESSAGE MUST SAY SO. This check runs against THIS
    PROCESS's copy of the IANA database, which is one of three in play and is not the one that
    speaks for the row. It is the last line of defence rather than the primary gate: the route
    checks the offered set first, and the offered set is built so that a name reaching here has
    already passed both databases. This still validates, because a module callable from anywhere
    validates its own inputs.

    THE MESSAGE USED TO BE A NEAR-COPY OF THE TRIGGER'S, AND THAT WAS THE THIRD DEFECT IN THIS
    CONTROL. It read "timezone 'X' does not resolve. Every slot, and therefore every action's
    as_of, is computed in this zone", which is the sentence synapse.provision's BEFORE INSERT
    trigger raises. On staging that 422 was produced HERE, by Python's tzdata, for
    ``Asia/Calcutta`` -- a name Postgres would have ACCEPTED. So the console attributed a refusal
    to a database that never saw the value and would not have objected to it, in a module whose
    own comments argue the trigger is the only authority that speaks for the database the row
    lands in.

    The wording below names which of the three databases refused, says the other two were not
    reached, and names the deprecated-alias cause without translating anything. The trigger's own
    message still passes through verbatim on the DBAPIError path in ``enable_analysis``; that one
    really is the database speaking.
    """
    declared = declared_analysis_ids()
    if analysis_id not in declared:
        raise EnablementRefusedError(
            f"{analysis_id!r} is not a declared analysis. Synapse declares {list(declared)}. "
            "Provisioning an undeclared id would not fail here: the orchestrator refuses the "
            "WHOLE enumeration when it loads the table, so the 04:00 sweep would stop for every "
            "tenant, not just this one",
            reason="unknown_analysis",
        )
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise EnablementRefusedError(
            f"timezone {timezone!r} was refused by THIS SERVICE's copy of the IANA database "
            "(Python's zoneinfo). It was not refused by Postgres and not by synapse.provision's "
            "trigger: neither was reached, and Postgres may well accept this name. The likeliest "
            "cause is a DEPRECATED IANA ALIAS, which this service's tzdata omits while other tz "
            "databases still carry it; the same zone almost always has a current name that is "
            "offered. Pick from the list this service serves at /timezones, which is the "
            "intersection of what this service and this database both accept. That list is the "
            "only set of names guaranteed to write",
            reason="bad_timezone",
        ) from exc


async def enable_analysis(
    engine: AsyncEngine,
    *,
    tenant_id: UUID,
    analysis_id: str,
    timezone: str,
    enabled_at: datetime,
) -> EnableOutcome:
    """Pre-flight and enable, in one transaction. Returns what became true.

    ``rls_session``, NOT ``rls_platform_session``, and that is forced rather than chosen: the
    policy's ``WITH CHECK`` compares ``app.tenant_id``, so a PLATFORM session sets the tenant GUC
    to '' and the insert matches no row and is refused. It is also what makes the WARN branch's
    count real, since canonical is FORCE RLS. One session helper satisfies both requirements and
    the other satisfies neither.

    ONE TRANSACTION, WHICH IS WHY THE PRE-FLIGHT IS A GATE RATHER THAN ADVICE. ``rls_session``
    commits on clean exit and rolls back on exception, so the FATAL branch raising here leaves
    nothing behind. Splitting it into a check followed by a write would leave a window, and the
    window is precisely where a checked-then-changed fact lives.

    ``enabled_at`` IS INJECTED, never read from a clock here. It is the start of the attribution
    window, stamped once and never edited, and a function that reads the clock cannot be tested
    at a boundary. Same rule as ``lifecycle.record_decision``'s ``recorded_at``.
    """
    _validate(analysis_id, timezone)

    async with rls_session(engine, tenant_id) as conn:
        name = (await conn.execute(_TENANT_NAME, {"tenant_id": str(tenant_id)})).scalar_one_or_none()
        if name is None:
            # FATAL. Raising inside the context manager rolls the transaction back, so this is
            # the same guarantee the psql file gets from RAISE inside BEGIN.
            raise EnablementRefusedError(
                f"tenant {tenant_id} is not in identity_mirror.tenants. Either the tenant has "
                "not been mirrored yet, or this request did not come from the fleet list. NOT "
                "provisioning: an unknown tenant produces a healthy-looking run with zero "
                "actions every day and never goes red",
                reason="unknown_tenant",
            )

        positions = int((await conn.execute(_POSITION_COUNT, {"tenant_id": str(tenant_id)})).scalar_one())

        try:
            await conn.execute(
                _ENABLE,
                {
                    "tenant_id": str(tenant_id),
                    "analysis_id": analysis_id,
                    "cadence": CADENCE,
                    "rung": RUNG,
                    "timezone": timezone,
                    "enabled_at": enabled_at,
                },
            )
        except DBAPIError as exc:
            # THE TRIGGER'S OWN MESSAGE, PASSED THROUGH. It names the column, the value and the
            # consequence ("Every slot, and therefore every action as_of, is computed in this
            # zone"), which is more than this module knows. Replacing it with a generic sentence
            # would be the console telling an operator less than the database told it.
            #
            # REACHED WHEN THE TWO TIMEZONE DATABASES DISAGREE, which is not hypothetical: the
            # browser offering the choice can carry a newer IANA release than the Postgres server,
            # so a zone can be offerable and unresolvable at the same time. _validate above uses
            # Python's tzdata, which is a third. The trigger is the only one that speaks for the
            # database the row lands in.
            if _is_unresolvable_timezone(exc):
                raise EnablementRefusedError(
                    str(getattr(exc, "orig", exc)).strip(), reason="bad_timezone"
                ) from exc
            raise

    warning = None
    if positions == 0:
        warning = (
            f'"{name}" has no canonical positions. Enabled anyway, which is correct if ingestion '
            "is still to come: every run until then will legitimately produce nothing. If you "
            "expected data, check ingestion before trusting the runs"
        )

    return EnableOutcome(
        analysis_id=analysis_id,
        tenant_name=str(name),
        canonical_positions=positions,
        warning=warning,
    )


def _is_unresolvable_timezone(exc: DBAPIError) -> bool:
    """Is this the timezone trigger firing, or something else?

    MATCHED ON SQLSTATE, NOT ON MESSAGE TEXT. The trigger raises with an explicit
    ``USING ERRCODE = 'invalid_parameter_value'`` (22023), which is a contract; its wording is
    prose that has already been edited once, when a stray ``%L`` was printing
    'Mars/Olympus_MonsL'. Matching the sentence would break the next time somebody improves it.

    Anything else re-raises untouched. An RLS violation, a CHECK failure or a lost connection are
    not this, and dressing them up as a bad timezone would send an operator to fix the wrong thing.
    """
    return getattr(getattr(exc, "orig", None), "sqlstate", None) == "22023"
