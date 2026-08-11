"""Every database read the delivery ledger surface performs. All SELECT, all PLATFORM.

TWO READS, AND THE SECOND IS NOT AN OPTIMISATION. The list is capped; the counts are not.
Deriving the counts from the returned page would understate every figure the moment the cap
bites, which is the defect the alerts inbox already records: a chip computed from a limited page
is a floor presented as a total. So the aggregate is its own query over the whole ledger.

=================================================================================================
THE SESSION POSTURE, PER TABLE, BECAUSE THE TWO TABLES DIFFER
=================================================================================================
Both reads open ``rls_platform_session(engine, None)``. What that means is NOT the same on each
side of the union, and both halves are worth stating:

  axon.platform_deliveries has NO row level security. No policy is consulted and the GUCs this
  helper sets are inert for it. The helper is used anyway, because it carries dis-rls's FIRST-USE
  POSTURE GUARD: on the first use of an engine it verifies the target database is the expected
  one and that the role is NOSUPERUSER NOBYPASSRLS. A reader that had quietly acquired a
  bypassing role would defeat the tenant ledger's isolation on the other half of every union
  below, and this is where that is caught.

  axon.tenant_deliveries is FORCE ROW LEVEL SECURITY. Its policy's USING carries the
  unconditional PLATFORM branch, so under this helper (app.user_type='PLATFORM') it matches every
  row and the fleet-wide read works. Its WITH CHECK does NOT carry that branch, and this helper
  sets app.tenant_id to '', so a write would compare tenant_id against NULL and match nothing.
  THIS SESSION READS EVERYTHING AND CAN WRITE NOTHING. That is the same property synapse's
  reads.py relies on for every console read, and it is why a read path and a write path here
  cannot share one session helper.

NOTHING IN THIS MODULE OPENS A RAW CONNECTION. Under FORCE RLS a session without app.user_type
matches ZERO ROWS AND RAISES NOTHING, for the table owner and for Cloud SQL's postgres alike.
synapse's reads.py counts six incidents in this project from that silent zero; there have been
five more in two days, one of them on a DELETE as the table owner.

=================================================================================================
NO user_type DISPATCH, AND THAT IS HALF OF CM'S COMPLEXITY THIS MODULE DOES NOT NEED
=================================================================================================
Customer Master's audit-log repo dispatches on the caller's audience: a TENANT caller must never
execute the platform-side query, because that table has no RLS and the application-layer routing
is the only barrier there is.

This surface is served by synapse-ui-server, where every read route is gated on
``require_platform``. There is no TENANT caller, so there is no dispatch and it is always the
union. If a tenant-facing console is ever built, the dispatch arrives WITH it, and it arrives as
a guard rather than a filter for exactly CM's reason.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from dis_rls import rls_platform_session

__all__ = [
    "DeliveryCounts",
    "DeliveryRow",
    "delivery_counts",
    "recent_deliveries",
]

# The list cap. A ledger grows without bound and a console page is not the place to discover
# that; the surface says when it is truncated rather than quietly showing a page and implying it
# is everything.
_MAX_ROWS = 200


@dataclass(frozen=True)
class DeliveryRow:
    """One delivery, from either ledger.

    ``scope`` IS SYNTHESISED BY THE QUERY, not stored. It is the only way a reader of a merged
    result can tell which table a row came from, and it is what lets one rendering serve both
    without a second query. Same device CM's audit union uses.

    ``tenant_id`` IS None FOR EVERY PLATFORM ROW, by construction rather than by accident:
    axon.platform_deliveries has no such column, because a platform delivery has no tenant.
    """

    scope: str
    delivery_id: UUID
    tenant_id: UUID | None
    created_at: datetime
    channel: str
    notification_class: str
    subject_kind: str
    subject_id: str
    recipient: str
    state: str
    suppression_reason: str | None
    provider: str
    failure_detail: str | None
    actor_subject: str | None


@dataclass(frozen=True)
class DeliveryCounts:
    """Fleet-wide totals, computed over the WHOLE ledger rather than over a page.

    ``suppressed_not_onboarded`` IS BROKEN OUT FROM ``suppressed`` DELIBERATELY. It is the one
    suppression reason that means a CLIENT is silently receiving nothing while the platform
    believes it is working: the operator sees a suppressed row, the client sees no message, and
    nothing prompts anybody. Counting it beside the others would bury the only one that needs a
    person.

    IT READS ZERO TODAY AND CANNOT READ ANYTHING ELSE. No tenant channel exists to be
    unonboarded, so the first non-zero value this ever shows will also be the first evidence that
    the query is right. Stated here rather than discovered later.
    """

    total: int
    accepted: int
    failed: int
    suppressed: int
    suppressed_not_onboarded: int


# =================================================================================================
# THE UNION. One statement, both audiences, newest first.
# =================================================================================================
# UNION ALL, NOT UNION. The two tables share a primary key space by construction (a UUIDv7 minted
# per delivery) and a row exists in exactly one of them, so there is nothing to deduplicate and
# UNION would pay for a distinct pass that can never remove a row.
#
# THE PLATFORM BRANCH SELECTS NULL::uuid AS tenant_id. Not because the value is unknown, but
# because the column does not exist: a platform delivery has no tenant. The cast is explicit so
# the union's column types resolve without depending on which branch Postgres reads first.
#
# -------------------------------------------------------------------------------------------------
# THE TENANT BRANCH SEQUENTIAL-SCANS, AND THE FIX IS NAMED SO IT IS NOT REDISCOVERED AS A MYSTERY
# -------------------------------------------------------------------------------------------------
# The ORDER BY below is global over the union. The platform side can serve it from
# ix_platform_deliveries_created_at, which is (created_at DESC, delivery_id DESC). The tenant side
# CANNOT: its only ordering index is ix_tenant_deliveries_tenant_created_at, which LEADS WITH
# tenant_id, so a query with no tenant predicate cannot use it for ordering and Postgres will
# sequential-scan and sort.
#
# THAT COSTS NOTHING TODAY, because axon.tenant_deliveries holds zero rows and can hold none:
# there is no address book, no tenant credential and no adapter beyond email. Adding an index to
# an empty table would be speculative work.
#
# THE FIX, WHEN IT IS NEEDED:
#
#     CREATE INDEX ix_tenant_deliveries_created_at
#         ON axon.tenant_deliveries (created_at DESC, delivery_id DESC);
#
# THE TRIGGER IS THE FIRST TENANT SENDS. Not a row count, not a slow query report: the moment
# anything writes axon.tenant_deliveries, this ORDER BY starts scanning a growing table. One line,
# in a migration 0002, at that point.
_RECENT = text(
    """
    SELECT 'PLATFORM'      AS scope,
           delivery_id,
           NULL::uuid      AS tenant_id,
           created_at,
           channel,
           notification_class,
           subject_kind,
           subject_id,
           recipient,
           state,
           suppression_reason,
           provider,
           failure_detail,
           actor_subject
      FROM axon.platform_deliveries
    UNION ALL
    SELECT 'TENANT'        AS scope,
           delivery_id,
           tenant_id,
           created_at,
           channel,
           notification_class,
           subject_kind,
           subject_id,
           recipient,
           state,
           suppression_reason,
           provider,
           failure_detail,
           actor_subject
      FROM axon.tenant_deliveries
     ORDER BY created_at DESC, delivery_id DESC
     LIMIT :limit
    """
)


# THE COUNTS, OVER THE WHOLE LEDGER. Filtered identically to nothing: this counts every row on
# both sides, which is what makes the totals comparable to a list that is merely capped rather
# than filtered. A count and a list that disagree about their scope read as a bug even when both
# numbers are right, which is the trap the alerts inbox's fleet-wide chips document.
#
# COUNTED WITH FILTERED AGGREGATES rather than four queries or a GROUP BY the caller reassembles:
# one pass, one row out, and the vocabulary appears once so a state added to the CHECK constraint
# without being added here shows up as a total that does not equal its parts.
_COUNTS = text(
    """
    WITH all_deliveries AS (
        SELECT state, suppression_reason FROM axon.platform_deliveries
        UNION ALL
        SELECT state, suppression_reason FROM axon.tenant_deliveries
    )
    SELECT count(*)                                                   AS total,
           count(*) FILTER (WHERE state = 'accepted')                 AS accepted,
           count(*) FILTER (WHERE state = 'failed')                   AS failed,
           count(*) FILTER (WHERE state = 'suppressed')               AS suppressed,
           count(*) FILTER (
               WHERE state = 'suppressed'
                 AND suppression_reason = 'channel_not_onboarded'
           )                                                          AS suppressed_not_onboarded
      FROM all_deliveries
    """
)


async def recent_deliveries(engine: AsyncEngine) -> tuple[tuple[DeliveryRow, ...], bool]:
    """The newest deliveries across both ledgers, and whether the result is truncated.

    RETURNS THE TRUNCATION FLAG RATHER THAN LEAVING IT TO BE INFERRED. A caller comparing
    len(rows) to a limit it also holds is two copies of one fact; the second copy is the one that
    goes stale when the limit moves.

    Session posture: ``rls_platform_session(engine, None)``. See the module docstring for what
    that means on each side of the union, and why nothing here opens a raw connection.
    """
    async with rls_platform_session(engine, None) as conn:
        rows = (await conn.execute(_RECENT, {"limit": _MAX_ROWS})).mappings().all()
    return (
        tuple(
            DeliveryRow(
                scope=row["scope"],
                delivery_id=row["delivery_id"],
                tenant_id=row["tenant_id"],
                created_at=row["created_at"],
                channel=row["channel"],
                notification_class=row["notification_class"],
                subject_kind=row["subject_kind"],
                subject_id=row["subject_id"],
                recipient=row["recipient"],
                state=row["state"],
                suppression_reason=row["suppression_reason"],
                provider=row["provider"],
                failure_detail=row["failure_detail"],
                actor_subject=row["actor_subject"],
            )
            for row in rows
        ),
        len(rows) >= _MAX_ROWS,
    )


async def delivery_counts(engine: AsyncEngine) -> DeliveryCounts:
    """Fleet-wide totals over the whole ledger, not over a page.

    Session posture: identical to ``recent_deliveries``, and it has to be. Two reads of the same
    tables under different postures would be two answers about one ledger, and under FORCE RLS
    the disagreement would be silent: the count could come back complete while the list came back
    empty, or the reverse.
    """
    async with rls_platform_session(engine, None) as conn:
        row = (await conn.execute(_COUNTS)).mappings().one()
    return DeliveryCounts(
        total=int(row["total"]),
        accepted=int(row["accepted"]),
        failed=int(row["failed"]),
        suppressed=int(row["suppressed"]),
        suppressed_not_onboarded=int(row["suppressed_not_onboarded"]),
    )
