"""Per-tenant data freshness, emitted as a log line every sweep so an ABSENCE becomes a NUMBER.

===============================================================================================
WHY THIS EXISTS: THE FAILURE NO EXECUTION-STATUS ALERT CAN SEE
===============================================================================================
A tenant whose data stopped arriving produces runs that SUCCEED, daily, for ever. The analyses
refuse per series, the run completes, ``synapse.run.outcome`` is ``satisfied``, the Cloud Run job
exits 0. Every execution-status signal in the system is green. The only thing that is wrong is
that a number stopped moving, and nothing in Cloud Monitoring can see a number that lives in
Postgres.

``satisfied`` DOES NOT MEAN "FOUND SOMETHING". It means every capability requirement RESOLVED —
see ``DeclarationStatus`` in core/declaration_resolution.py. So a stale tenant is
``satisfied`` with ``actions_proposed=0``, which is byte-identical to a healthy day on which
nothing was at risk. That is the same ambiguity the console renders as "0 · reason not recorded",
and it is why a log-based alert on ``actions_proposed=0`` would fire on perfectly good days.

THE TECHNIQUE: MAKE THE ABSENCE EMIT A POSITIVE NUMBER. Rather than trying to alert on the
absence of something, emit the age of the newest fact every single sweep and threshold that. An
absence signal that is itself absent when things are healthy cannot be thresholded — there would
be no series to compare against, no way to tell "fresh" from "the exporter stopped".

SO IT IS EMITTED FOR EVERY SWEPT TENANT, INCLUDING HEALTHY ONES. That is deliberate and it is
the whole reason this is thresholdable.

===============================================================================================
WHY A QUERY, WHEN dead_stock ALREADY FETCHES THE SALE DATE
===============================================================================================
Asked directly: is the number already in hand? For ``dead_stock`` it is fetched — the
``last_sale_at`` capability yields ``LastSaleAtRow.last_sale_date`` per (tenant, store, sku), so
``max()`` over those rows is the tenant's latest sale. For ``stockout_risk`` the ``daily_series``
capability yields ``DailySeriesRow.event_date``, so ``max()`` over ITS rows would do the same —
but only WITHIN ITS WINDOW (``window_days``, 28 and 14 for the current analyses). A tenant stale beyond the
window resolves to an EMPTY series, which is exactly the case worth reporting and exactly the
case where the number is missing.

BUT THE DECIDING CONSTRAINT IS ARCHITECTURAL, NOT ABOUT WINDOWS. The rows are not in hand AT THE
LAYER THAT CAN LOG THEM. ``runner._run_one`` holds a ``DeclarationSatisfied``, which carries
``fetch`` CALLABLES, not rows; the PLAN fetches, inside ``_propose``. ``Satisfied.fetch`` is a
bare ``Callable[[], Awaitable[...]]`` with no memoisation, so calling it from the runner to read
the number would issue a SECOND full series read, not reuse the first. And threading the value
back out of the plan is a Plan-signature change. Doing it here would silently take on that
larger change.

DEAD_STOCK DOES EXACTLY WHAT THE FIRST PARAGRAPH DESCRIBES, AND THIS MODULE IS UNAFFECTED BY
IT. ``synapse.core.dead_stock._feed_refusal`` takes ``max()`` over the ``last_sale_at`` rows the
plan already fetched and refuses the sweep when the tenant's newest sale is too old. That does
not make this module redundant and does not contradict the paragraph above: the blocker named
there is that the ROWS ARE NOT IN HAND AT THE LAYER THAT CAN LOG THEM, and that is still true.
The PLAN has the rows; the runner does not, and this metric must be emitted for every swept
tenant including ones running no dead_stock at all. Two consumers of one fact, at two layers,
computed where each can reach it.

THE THRESHOLDS AGREE AND MUST STAY AGREEING. ``STALE_AFTER_DAYS`` below, dead_stock's
``feed_stale_after_days``, stockout_risk's ``stale_after_days`` and the fleet roster's column all
say 3 days, strictly greater. A change to one without the others makes an alert fire while a
screen reads healthy.

So: ONE AGGREGATE PER TENANT PER SWEEP, and it lives in
``synapse.resolvers.sale_freshness`` — NOT here. Only resolvers may name a canonical table
(enforced by tests/unit/test_table_name_containment.py). See the resolver for the cost.

PER TENANT, NOT PER PAIR. Freshness is a property of the tenant's DATA, not of any (tenant,
analysis) pair. A tenant with both analyses provisioned would otherwise emit the same number
twice and double every count built on it.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncEngine

from synapse.resolvers.sale_freshness import resolve_latest_sale_dates

__all__ = ["TenantFreshness", "emit_tenant_freshness", "tenant_freshness"]

_log = logging.getLogger("synapse.orchestrator.freshness")

# The strictest freshness threshold any analysis declares, and the same number the fleet screen
# uses (cm-frontend R1's STALE_AFTER_DAYS). NOT WIDENED TO STOP THE ALERT FIRING: The Body Shop is
# 17 days stale today, so the alert built on this is red from creation. Widening a threshold so it
# does not fire is tuning the alert to make the demo work — the same reasoning that fixed slice
# 7's gate at 7 days rather than moving it to fit the data.
STALE_AFTER_DAYS = 3


@dataclass(frozen=True)
class TenantFreshness:
    """One tenant's newest sale, and how old it is.

    A value rather than a log line, so a test can assert on the number without parsing text —
    the same reason ``SlotResult`` is a value.
    """

    tenant_id: UUID
    latest_sale: date | None
    # Days since the newest sale. When no sale has EVER arrived this is days since the tenant was
    # provisioned instead — see ``ever_sold``.
    age_days: int
    # False when the tenant has never sent a sale. The distinction matters: "stopped sending" and
    # "never started" need different actions, and a NULL age would produce no metric point at all,
    # so the threshold could never fire for the tenant that has sent nothing.
    ever_sold: bool

    @property
    def stale(self) -> bool:
        return self.age_days > STALE_AFTER_DAYS


async def tenant_freshness(
    reader_engine: AsyncEngine,
    *,
    enabled_at: Mapping[UUID, datetime],
    now: datetime,
) -> tuple[TenantFreshness, ...]:
    """One row per tenant in ``enabled_at``, newest-sale first.

    ``now`` IS A PARAMETER, never read from the clock in here — the same discipline as ``run_due``
    and for the same payoff: "how stale was this tenant on the 1st" is answerable and a threshold
    boundary is testable without waiting a day.
    """
    latest = await resolve_latest_sale_dates(reader_engine, enabled_at.keys())
    today = now.astimezone(UTC).date()
    out: list[TenantFreshness] = []
    for tenant_id, provisioned in enabled_at.items():
        sale = latest.get(tenant_id)
        if sale is None:
            # NEVER SOLD. The age is how long we have been watching and seen nothing, which is the
            # honest measure and is thresholdable; a NULL would emit no metric point at all and the
            # alert would be blind to exactly the tenant for which nothing has ever worked.
            out.append(
                TenantFreshness(
                    tenant_id=tenant_id,
                    latest_sale=None,
                    age_days=max(0, (now - provisioned).days),
                    ever_sold=False,
                )
            )
        else:
            out.append(
                TenantFreshness(
                    tenant_id=tenant_id,
                    latest_sale=sale,
                    age_days=(today - sale).days,
                    ever_sold=True,
                )
            )
    return tuple(sorted(out, key=lambda f: (-f.age_days, str(f.tenant_id))))


def emit_tenant_freshness(freshness: Iterable[TenantFreshness]) -> None:
    """One structured entry per tenant. The FIELD is what the metric reads; severity is for humans.

    ``jsonPayload.sale_age_days`` is the value the log-based metric extracts. Verified shape:
    ``dis_core.logging`` flattens ``extra`` to the TOP LEVEL of the JSON payload, so the extractor
    path is ``EXTRACT(jsonPayload.sale_age_days)`` and not a nested one. (Proven by running the
    logger, not by reading it — a nested path would silently extract nothing and the metric would
    have no data while looking configured.)

    WARNING when stale, INFO when fresh, and the metric reads the value either way — so the series
    exists on healthy days, which is what makes it thresholdable. The severity is a second,
    human-readable signal and deliberately NOT what the alert matches: matching severity would
    make the alert fire on the log line's opinion rather than on the number.
    """
    for entry in freshness:
        fields = {
            "tenant_id": str(entry.tenant_id),
            "latest_sale": entry.latest_sale.isoformat() if entry.latest_sale else None,
            "sale_age_days": entry.age_days,
            "ever_sold": entry.ever_sold,
            "stale": entry.stale,
            "stale_after_days": STALE_AFTER_DAYS,
        }
        if not entry.ever_sold:
            message = f"tenant {entry.tenant_id} has never sent a sale ({entry.age_days}d since provisioning)"
        else:
            message = f"tenant {entry.tenant_id} last sale {entry.latest_sale} ({entry.age_days}d old)"
        if entry.stale:
            _log.warning(f"{message} — every rate-based analysis is refusing", extra=fields)
        else:
            _log.info(message, extra=fields)
