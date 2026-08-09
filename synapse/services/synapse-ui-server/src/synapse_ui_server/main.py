"""The app. PLATFORM routes over one reader engine, plus two narrow write paths.

TWO WRITES, TWO CREDENTIALS, AND NEITHER CAN DO THE OTHER'S JOB. ``lifecycle`` appends an operator
decision to ``synapse.action_events`` as ``synapse_lifecycle`` (5d); ``provision`` enables one
analysis for one tenant in ``synapse.provision`` as ``synapse_provisioner`` (5e). Three engines,
three roles, and the reader serves every GET.

WHAT ``/readyz`` PROVES, and it is deliberately more than "the process is up": it opens a real
PLATFORM session, which exercises dis-rls's first-use guard — the target database is the expected
one and the role is NOSUPERUSER NOBYPASSRLS. A revision pointed at the wrong database, or holding
a role that can bypass RLS, fails readiness instead of serving a console that silently shows the
wrong tenants or trusts a credential that can see everything.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, date, datetime
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from dis_core.logging import configure_logging, get_logger
from dis_rls import create_rls_engine, rls_platform_session
from synapse_ui_server import catalog, reads
from synapse_ui_server.auth import Auth0Verifier, AuthError, Identity, require_platform
from synapse_ui_server.cm_permissions import require_tenant_configure
from synapse_ui_server.config import Config, load_config
from synapse_ui_server.lifecycle import (
    Decision,
    DismissReason,
    LifecycleVerb,
    record_decision,
)
from synapse_ui_server.provision import (
    CADENCE,
    RUNG,
    EnablementRefusedError,
    enable_analysis,
)
from synapse_ui_server.timezones import load_offered

# RE-EXPORTED so tests can patch the name THIS module calls. A test that patched
# provision.enable_analysis instead would pass against a main.py that had stopped calling it.
__all__ = ["EnableBody", "create_app", "enable_analysis"]


class DecisionBody(BaseModel):
    """What the console posts. Typed loosely as str so an unknown member is refused by the
    enum with a message naming the legal set, rather than by pydantic with a schema error the
    operator cannot act on."""

    verb: str
    reason: str | None = None
    snoozed_until: date | None = None


class EnableBody(BaseModel):
    """What the console posts to enable a monitor. ONE FIELD, AND THE OMISSIONS ARE THE CONTRACT.

    THERE IS NO ``cadence`` AND NO ``rung`` HERE, and adding either would be the defect. They are
    constants in provision.py, and the reason is blast radius rather than tidiness: the envelope
    check runs when the ORCHESTRATOR LOADS the table and refuses the WHOLE ENUMERATION, so one
    wrong rung stops the 04:00 sweep for every tenant. The DDL permits 'suggest' and nothing
    implements it, so a field here backed by the CHECK constraint would accept a fleet-breaking
    value that passes every database constraint.

    THERE IS NO ``tenant_id`` AND NO ``analysis_id`` EITHER. Both are path parameters, and both
    reach the path from a LIST rather than a text field: the tenant from the fleet roster, the
    analysis from the registry catalogue the same page already renders. An unknown tenant produces
    a healthy run with zero actions for ever, and an undeclared analysis stops the whole sweep;
    neither should be typeable.

    THERE IS NO WAY TO CHANGE AN EXISTING TIMEZONE. This body is only read on the enable path, and
    that path refuses a pair that already exists. The zone feeds every action's ``as_of``, which
    sits inside an append-only idempotency index that cannot be re-keyed.
    """

    timezone: str


_log = get_logger("synapse-ui-server")

_REASON_STATUS = {"missing": 401, "invalid": 401, "forbidden": 403}

# EnablementRefusedError.reason to HTTP status. A MAPPING RATHER THAN A CHAIN OF ifs, so a reason added
# to provision.py without a decision here fails loudly on the .get() default rather than being
# filed under 422 by accident.
#
#   unknown_tenant   404. The tenant is not in the mirror, which is the same answer every other
#                    route here gives for an id it cannot resolve.
#   unknown_analysis 404. The path named an analysis that does not exist. Not 422: the id is a
#                    path segment naming a resource, and a client that reached it from the
#                    catalogue cannot produce this.
#   bad_timezone     422. The request was understood and refused, and the message names why.
_PROVISION_REFUSAL_STATUS = {
    "unknown_tenant": 404,
    "unknown_analysis": 404,
    "bad_timezone": 422,
}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    config: Config = app.state.config
    # THREE ENGINES, THREE CREDENTIALS, AND THE SPLIT IS THE SAFETY. The reader serves every GET.
    # The lifecycle engine exists only for lifecycle.record_decision and connects as a role holding
    # INSERT on synapse.action_events and nothing else. The provision engine exists only for
    # provision.enable_analysis and connects as a role holding INSERT on synapse.provision plus the
    # two SELECTs its pre-flight cannot run without.
    #
    # NONE CAN DO ANOTHER'S JOB. The reader cannot write anywhere. The lifecycle role cannot read
    # a single row. The provisioner cannot read the action log, cannot read back its own table,
    # and holds no UPDATE, so it cannot disable a tenant or edit a timezone.
    #
    # THREE IS NOT A TREND TOWARD ONE WIDE ROLE. Each is one verb on one table because that is the
    # only shape in which "what this service can do" is a fact about the database rather than a
    # claim about the code.
    app.state.engine = create_rls_engine(config.reader_url)
    app.state.lifecycle_engine = create_rls_engine(config.lifecycle_url)
    app.state.provision_engine = create_rls_engine(config.provision_url)
    app.state.verifier = getattr(app.state, "verifier", None) or Auth0Verifier(
        jwks_url=config.jwks_url, issuer=config.jwt_issuer, audience=config.jwt_audience
    )

    # THE TIMEZONE PICKER'S LIST, computed ONCE, here, against the database this service actually
    # writes to. See timezones.py: it is the intersection of what this process can resolve and
    # what this Postgres accepts, so a name the console offers cannot be one either side refuses.
    #
    # THIS MAKES STARTUP TOUCH THE DATABASE, which is a new failure mode on a path that had none.
    # load_offered never raises: it falls back to Python's set alone and logs at WARNING. A broken
    # picker beats a dead console, and /readyz below keeps its own independent session so a
    # genuinely dead database still fails readiness through the check that exists for it.
    app.state.timezones = await load_offered(app.state.engine)
    _log.info(
        "synapse-ui-server ready",
        extra={
            "read_only": False,
            "write_surface": ("synapse.action_events (insert only), synapse.provision (insert only)"),
        },
    )
    try:
        yield
    finally:
        await app.state.engine.dispose()
        await app.state.lifecycle_engine.dispose()
        await app.state.provision_engine.dispose()


def create_app(config: Config | None = None) -> FastAPI:
    # NO SCHEMA ENDPOINTS. /docs, /redoc and /openapi.json are the only routes
    # FastAPI mounts without a dependency, so any caller able to invoke this
    # service could enumerate its API without being PLATFORM.
    #
    # NOT BECAUSE OF TODAY'S RISK. Because this service is the PRECEDENT for
    # fixing the other four, and "safe behind two layers" is exactly how a public
    # schema happens on the day one layer changes — an ingress setting relaxed for
    # a debugging session, a binding widened to unblock something.
    #
    # THAT DAY WAS 2026-08-05, AND THIS COMMENT PREDICTED ITS OWN FALSIFICATION.
    # It used to open "NOT BECAUSE OF TODAY'S RISK, which behind INTERNAL INGRESS
    # plus an IAM invoker binding is genuinely low" — and then ingress was relaxed
    # to INGRESS_TRAFFIC_ALL, by exactly the mechanism the sentence below names,
    # because INTERNAL_ONLY was never satisfiable by the only caller. So the
    # premise went stale while the conclusion it argued for became MORE load-
    # bearing, not less: one of the two layers is gone, IAM is the remaining
    # network-layer control, and keeping the schema off this service is now doing
    # real work rather than being belt-and-braces.
    #
    # Left in place as the record. A comment that names the condition under which
    # it stops being true is worth more than one that is merely correct today —
    # but it still goes stale silently, because nothing re-reads it when the
    # condition fires.
    #
    # There is no consumer to lose: cm-frontend is the only caller and it is
    # server-side, with its request shapes typed in lib/synapse/*.
    app = FastAPI(
        title="synapse-ui-server",
        lifespan=_lifespan,
        # openapi_url=None IS THE LOAD-BEARING ONE: FastAPI only mounts /docs and
        # /redoc when a schema URL exists, so this alone removes all three. The other
        # two are declared anyway — they state the intent at the call site, and a
        # future FastAPI that decoupled them would otherwise reintroduce the UIs
        # silently. (Verified: deleting docs_url alone changes nothing; deleting
        # openapi_url fails the test below.)
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )
    app.state.config = config or load_config()

    @app.exception_handler(AuthError)
    async def _auth_error(request: Request, exc: AuthError) -> JSONResponse:
        # The reason, never the token and never a claim value. A rejected credential echoed into
        # a log is a credential in Cloud Logging for the bucket's lifetime.
        _log.warning("request rejected", extra={"reason": exc.reason, "path": request.url.path})
        return JSONResponse(
            status_code=_REASON_STATUS.get(exc.reason, 401),
            content={"error": {"reason": exc.reason, "message": str(exc)}},
        )

    @app.get("/healthz")
    async def healthz() -> dict[str, str]:
        """Liveness. Deliberately touches no database: a dead pool should not restart the pod."""
        return {"status": "ok"}

    @app.get("/readyz")
    async def readyz(request: Request) -> dict[str, str]:
        """Readiness. Opens a PLATFORM session, so dis-rls's target and role guard actually runs."""
        async with rls_platform_session(request.app.state.engine, None):
            pass
        return {"status": "ready"}

    @app.get("/fleet")
    async def get_fleet(
        request: Request, _: Annotated[Identity, Depends(require_platform)]
    ) -> dict[str, object]:
        rows = await reads.fleet(request.app.state.engine)
        return {"tenants": [row.__dict__ for row in rows]}

    @app.get("/tenants/{tenant_id}")
    async def get_tenant(
        tenant_id: UUID, request: Request, _: Annotated[Identity, Depends(require_platform)]
    ) -> dict[str, object]:
        detail = await reads.tenant_detail(request.app.state.engine, tenant_id)
        if detail is None:
            # 404 rather than an empty shell: a mistyped id rendering zeros is indistinguishable
            # from a real tenant with nothing on, and that confusion has already cost this
            # project once.
            raise HTTPException(
                status_code=404,
                detail=f"{tenant_id} is not in identity_mirror.tenants",
            )
        return {
            **{k: v for k, v in detail.__dict__.items() if k != "analyses"},
            "analyses": [state.__dict__ for state in detail.analyses],
        }

    @app.get("/tenants/{tenant_id}/runs")
    async def get_tenant_runs(
        tenant_id: UUID,
        request: Request,
        _: Annotated[Identity, Depends(require_platform)],
        limit: int = 100,
    ) -> dict[str, object]:
        """One tenant's run history. Added alongside /runs, which is unchanged.

        404 ON AN UNKNOWN TENANT, matching /tenants/{tenant_id} above and for the same reason: an
        empty history for a mistyped id is indistinguishable from a real tenant that has never
        run, and that confusion has already cost this project once.
        """
        rows = await reads.tenant_runs(request.app.state.engine, tenant_id, limit=limit)
        if rows is None:
            raise HTTPException(
                status_code=404,
                detail=f"{tenant_id} is not in identity_mirror.tenants",
            )
        return {"runs": [row.__dict__ for row in rows]}

    @app.get("/tenants/{tenant_id}/alerts")
    async def get_tenant_alerts(
        tenant_id: UUID,
        request: Request,
        _: Annotated[Identity, Depends(require_platform)],
        limit: int = 100,
    ) -> dict[str, object]:
        """One tenant's recorded alerts, newest slot first.

        THE FIRST ENDPOINT IN THIS SERVICE THAT RETURNS PER-PRODUCT DATA. Everything before it
        counts actions; this lists them, because the console's Alerts section aggregated per
        monitor and there was no individual alert to open. PLATFORM only, like every route here —
        the payload carries sku_id, product_name and store_name, all of which
        tenant_view_contract forbids on a tenant-facing surface.

        404 ON AN UNKNOWN TENANT, matching /tenants/{tenant_id} and /tenants/{tenant_id}/runs.
        """
        rows = await reads.tenant_alerts(request.app.state.engine, tenant_id, limit=limit)
        if rows is None:
            raise HTTPException(
                status_code=404,
                detail=f"{tenant_id} is not in identity_mirror.tenants",
            )
        return {"alerts": [row.__dict__ for row in rows]}

    @app.get("/tenants/{tenant_id}/alerts/{event_id}")
    async def get_alert_detail(
        tenant_id: UUID,
        event_id: UUID,
        request: Request,
        _: Annotated[Identity, Depends(require_platform)],
    ) -> dict[str, object]:
        """One alert with its earlier raisings.

        404 COVERS BOTH "no such event" AND "that event belongs to another tenant", and the
        conflation is the point. Answering 403 for the mismatch would confirm the event exists
        under some other tenant — a cross-tenant existence oracle on a console that spans the
        fleet. The reader puts both predicates in one WHERE so the two cases are genuinely
        indistinguishable here rather than merely reported alike.
        """
        detail = await reads.alert_detail(request.app.state.engine, tenant_id, event_id)
        if detail is None:
            raise HTTPException(
                status_code=404,
                detail=f"no alert {event_id} for tenant {tenant_id}",
            )
        return {
            "alert": detail.alert.__dict__,
            "history": [row.__dict__ for row in detail.history],
        }

    @app.post("/tenants/{tenant_id}/alerts/{event_id}/decisions", status_code=201)
    async def record_alert_decision(
        tenant_id: UUID,
        event_id: UUID,
        body: DecisionBody,
        request: Request,
        identity: Annotated[Identity, Depends(require_platform)],
    ) -> dict[str, object]:
        """Record what an operator decided about an alert. THE ONLY WRITE THIS SERVICE MAKES.

        THE ALERT IS READ FIRST, THROUGH THE READER. Two reasons and both matter: it 404s a
        typo or another tenant's event before anything is written, and it is where the target
        grain comes from — the lifecycle credential holds INSERT and no SELECT, so this module
        physically cannot look the alert up with the same connection it writes on.

        THE DECISION APPLIES TO THE TARGET, NOT THE EVENT. A snooze means "this product at this
        store"; tomorrow's detection is a new event_id and must inherit it. The clicked event is
        recorded as provenance.

        THE ACTOR IS THE AUTH0 SUBJECT AND NOTHING MORE. The session carries no name or email
        claim, so that is the whole honest identity available.
        """
        detail = await reads.alert_detail(request.app.state.engine, tenant_id, event_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"no alert {event_id} for tenant {tenant_id}")

        try:
            decision = Decision(
                action_event_id=event_id,
                tenant_id=tenant_id,
                declaration_id=detail.alert.declaration_id,
                target=detail.alert.target,
                verb=LifecycleVerb(body.verb),
                reason=DismissReason(body.reason) if body.reason else None,
                snoozed_until=body.snoozed_until,
                actor_subject=identity.subject,
            )
        except ValueError as exc:
            # Covers both an unknown enum member and an illegal combination. 422, not 500: the
            # request was understood and refused, and the message names the legal set.
            raise HTTPException(status_code=422, detail=str(exc)) from exc

        lifecycle_event_id = await record_decision(
            request.app.state.lifecycle_engine, decision, recorded_at=datetime.now(UTC)
        )
        return {"lifecycle_event_id": str(lifecycle_event_id)}

    @app.post("/tenants/{tenant_id}/analyses/{analysis_id}/enable", status_code=201)
    async def enable_monitor(
        tenant_id: UUID,
        analysis_id: str,
        body: EnableBody,
        request: Request,
        identity: Annotated[Identity, Depends(require_tenant_configure)],
    ) -> dict[str, object]:
        """Enable one analysis for one tenant. THE SECOND WRITE THIS SERVICE MAKES.

        GATED ON A CUSTOMER MASTER PERMISSION, not on anything defined here. ``require_tenant_
        configure`` asks CM whether this caller holds ADMIN.TENANTS.CONFIGURE.GLOBAL and denies on
        any doubt, including a CM outage. Read that module before changing this line: the
        permission is KNOWN-BROADER than the act, deliberately, and 5e must not reach a production
        tenant until CM's enums carry a Synapse-specific one.

        ENABLE ONLY. There is no disable route and no re-enable route, and the absence is enforced
        three deep: no function in provision.py, no UPDATE in the synapse_provisioner grant, and
        the 409 below. ``synapse.provision`` holds ONE window per (tenant, analysis), so clearing
        ``disabled_at`` would lose the fact that there was a gap and the attribution denominator
        for that period would silently become wrong.

        THE STATE IS ESTABLISHED THROUGH THE READER FIRST, and that is forced rather than chosen.
        The provisioner credential holds no SELECT on the table it writes, so this handler
        physically cannot ask "is it already on" on the connection it writes with. The same split
        as the decisions route above, for the same reason.

        THREE STATES, THREE ANSWERS. Active is 409 "already enabled". Disabled is 409 naming the
        window and saying re-enabling is deliberately unavailable. Never provisioned proceeds. The
        third is not the default: treating disabled as never-provisioned would send an ON CONFLICT
        DO NOTHING at the database, get no error, and report success while changing nothing.
        """
        detail = await reads.tenant_detail(request.app.state.engine, tenant_id)
        if detail is None:
            raise HTTPException(status_code=404, detail=f"{tenant_id} is not in identity_mirror.tenants")

        if any(state.analysis_id == analysis_id for state in detail.analyses):
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{analysis_id} is already enabled for {detail.name}. Enabling is idempotent "
                    "at the database, so this changes nothing either way; it is reported rather "
                    "than swallowed so the console never shows a success that did nothing"
                ),
            )

        disabled = next((row for row in detail.disabled_analyses if row.analysis_id == analysis_id), None)
        if disabled is not None:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"{analysis_id} was enabled for {detail.name} on "
                    f"{disabled.enabled_at.date()} and disabled on {disabled.disabled_at.date()}. "
                    "Re-enabling is deliberately not available: this table holds one window per "
                    "tenant and analysis, so re-enabling would overwrite that window and the "
                    "attribution denominator for the gap would silently become wrong. Building "
                    "the append-only enablement history is the fix, and the first disable is its "
                    "trigger"
                ),
            )

        # THE OFFERED SET IS THE AUTHORITY ON WHAT CAN BE WRITTEN, and it is checked HERE rather
        # than in provision.py because it is runtime environment state: the intersection of two
        # tzdata builds, read at startup, held on app.state. A write module cannot see that and
        # should not import it.
        #
        # TWO CHECKS, IN THIS ORDER, AND THE ORDER IS THE MESSAGE. enable_analysis runs its own
        # ZoneInfo check as the last line of defence, because a module callable from anywhere
        # validates its own inputs; that one fires first for a DEPRECATED ALIAS like
        # Asia/Calcutta, which is the observed case, and its message explains which of the three
        # timezone databases refused. This check catches the remainder: a name this process can
        # resolve that Postgres will not, which is the direction the intersection exists to close.
        offered = request.app.state.timezones
        if not offered.offers(body.timezone):
            degraded = (
                " This list is DEGRADED: Postgres could not be read at startup, so it is this "
                "service's names alone and a zone on it may still be refused by the database."
                if offered.source == "python_only"
                else ""
            )
            raise HTTPException(
                status_code=422,
                detail=(
                    f"timezone {body.timezone!r} is not one this console offers. The offered list "
                    f"is the INTERSECTION of the names this service can resolve and the names "
                    f"this Postgres accepts, currently {len(offered.names)} of them, and it is "
                    "the only set guaranteed to write. A name outside it is refused rather than "
                    "translated: this column is immutable and feeds every action's as_of, so "
                    "silently storing a value nobody typed would be worse than refusing one. Pick "
                    f"from GET /timezones.{degraded}"
                ),
            )

        try:
            outcome = await enable_analysis(
                request.app.state.provision_engine,
                tenant_id=tenant_id,
                analysis_id=analysis_id,
                timezone=body.timezone,
                # THE START OF THE ATTRIBUTION WINDOW, stamped once here and never edited. Passed
                # in rather than defaulted in SQL so the value is the caller's observed instant
                # and the function stays testable at a boundary.
                enabled_at=datetime.now(UTC),
            )
        except EnablementRefusedError as exc:
            # .get WITH NO FALLBACK STATUS. A reason added to provision.py and not decided here
            # raises KeyError into the 500 handler, which is louder than quietly calling it a 422.
            raise HTTPException(status_code=_PROVISION_REFUSAL_STATUS[exc.reason], detail=str(exc)) from exc

        # ================================================================================
        # THE AUDIT RECORD FOR SLICE 5e, AND IT IS A LOG LINE, WHICH IS NOT ENOUGH
        # ================================================================================
        # WHAT IS RECORDED: who (the Auth0 subject, the only honest identity in the session),
        # which tenant, which analysis, which timezone, and what became true. synapse.provision
        # itself records WHEN via enabled_at and records nobody.
        #
        # WHY IT IS ONLY A LOG LINE. The right home is synapse.provision_events: append-only,
        # closed vocabulary, actor_subject, the same shape as synapse.action_events. That table IS
        # the append-only enablement history in disguise, and provision.sql names the first
        # DISABLE as its trigger rather than the first enable. Building it here would pre-empt a
        # deliberate deferral and would ship a second table for a case that has not happened.
        #
        # A 30-DAY LOG LINE IS NOT AN AUDIT RECORD. Cloud Logging's default retention is the
        # ceiling and the entry is not queryable as a record: nothing can answer "who enabled this
        # monitor" from the database, and after thirty days nothing can answer it at all.
        # Provisioning is a heavier decision than snoozing an alert and snoozing has a real row.
        #
        # SO THIS CARRIES THE SAME STANDING CONDITION AS THE KNOWN-BROADER PERMISSION:
        # 5e must not reach a production tenant until synapse.provision_events exists.
        # Staging is where a log line is an acceptable stand-in.
        #
        # `severity` NOTICE, never `levelname`. Cloud Logging files anything else at DEFAULT and
        # no alert can match it.
        _log.info(
            "analysis enabled",
            extra={
                "severity": "NOTICE",
                "event": "synapse.provision.enabled",
                "actor_subject": identity.subject,
                "tenant_id": str(tenant_id),
                "tenant_name": outcome.tenant_name,
                "analysis_id": outcome.analysis_id,
                "timezone": body.timezone,
                "cadence": CADENCE,
                "rung": RUNG,
                "canonical_positions": outcome.canonical_positions,
                "warned_no_positions": outcome.warning is not None,
            },
        )

        # THE CONFIGURATION IS ECHOED SO THE OPERATOR SEES WHAT THEY DID NOT CHOOSE. cadence and
        # rung were never theirs to set, and a response that omitted them would leave the console
        # unable to say "silent mode, daily" without restating a constant it cannot see.
        return {
            "analysis_id": outcome.analysis_id,
            "tenant_name": outcome.tenant_name,
            "timezone": body.timezone,
            "cadence": CADENCE,
            "rung": RUNG,
            "canonical_positions": outcome.canonical_positions,
            # NOT AN ERROR. Enabling ahead of ingestion is legitimate; the reason to say it is
            # that a monitor producing nothing for a week is otherwise indistinguishable from one
            # that is working and finding nothing.
            "warning": outcome.warning,
        }

    @app.get("/alerts/state-counts")
    async def get_alert_state_counts(
        request: Request, _: Annotated[Identity, Depends(require_platform)]
    ) -> dict[str, object]:
        """Fleet-wide alert counts per lifecycle state, for the inbox filter chips.

        DECLARED BEFORE /alerts, and the order is deliberate rather than cosmetic. FastAPI
        matches routes in declaration order, so if a parameterised sibling like
        /alerts/{event_id} is ever added above this one, the literal "state-counts" would be
        captured as that parameter and this endpoint would silently stop being reachable.

        NOT DERIVED FROM THE LIST. The list is paginated and these counts are not: computing
        chips from a returned page understates every number the moment the limit bites, and a
        chip that disagrees with the list it filters is worse than no chip at all.
        """
        return {"states": dict(await reads.alert_state_counts(request.app.state.engine))}

    @app.get("/alerts")
    async def get_alerts(
        request: Request,
        _: Annotated[Identity, Depends(require_platform)],
        state: str | None = None,
        analysis_id: str | None = None,
        tenant_id: UUID | None = None,
        store_id: UUID | None = None,
        limit: int = 100,
    ) -> dict[str, object]:
        """Every alert across the fleet, newest slot first, with optional filters.

        READS THE ANALYTICAL VIEW, not synapse.actions. Migration 0007 built
        synapse.actions_analytical to keep the sentinel fixture tenant's immortal probe rows out
        of analytical surfaces, and a fleet-wide inbox is precisely that: those rows would land
        in the default view and inflate the chip counts, arriving from a tenant nobody would
        think to look at.

        NO 404. An empty fleet and a filter matching nothing are both legitimate answers; there
        is no id here whose absence means the caller asked for something that does not exist.

        An unknown `state` value is not an error either: it simply matches nothing, which is what
        a filter is entitled to do.
        """
        rows = await reads.fleet_alerts(
            request.app.state.engine,
            state=state,
            analysis_id=analysis_id,
            tenant_id=tenant_id,
            store_id=store_id,
            limit=limit,
        )
        return {"alerts": [row.__dict__ for row in rows]}

    @app.get("/runs")
    async def get_runs(
        request: Request, _: Annotated[Identity, Depends(require_platform)], limit: int = 100
    ) -> dict[str, object]:
        rows = await reads.runs(request.app.state.engine, limit=limit)
        return {"runs": [row.__dict__ for row in rows]}

    @app.get("/capabilities")
    async def get_capabilities(
        _: Annotated[Identity, Depends(require_platform)],
    ) -> dict[str, object]:
        """In-process. No database, no probe — coverage per tenant is a separate lazy call."""
        return {"capabilities": [row.__dict__ for row in catalog.capabilities()]}

    @app.get("/timezones")
    async def get_timezones(
        request: Request, _: Annotated[Identity, Depends(require_platform)]
    ) -> dict[str, object]:
        """Every timezone name the console may offer for an enablement.

        THE INTERSECTION OF THIS SERVICE AND THIS DATABASE, computed once at startup. Slice 5e
        populated this picker from the BROWSER, whose list resolves through CLDR/ICU and so
        offered ``Asia/Calcutta`` while omitting ``Asia/Kolkata`` entirely: every enable was
        refused at validation and nothing could be provisioned. An intersection cannot contain a
        name either side rejects, which turns that from a thing to be careful about into a thing
        that cannot happen.

        NOT COMPUTED PER REQUEST. It is a property of the two tzdata builds in play, which do not
        change without a deploy or a database upgrade, and a per-request query would put a
        database round trip in front of opening a dropdown.

        ``source`` IS SERVED, not just logged. ``python_only`` means the Postgres half could not
        be read at startup, so a name here MIGHT still be refused by the trigger. The console
        renders that plainly rather than looking healthy: a fallback nobody can see is the same
        dead-control class in the opposite direction.
        """
        offered = request.app.state.timezones
        return {
            "timezones": list(offered.names),
            "source": offered.source,
            "count": len(offered.names),
        }

    @app.get("/analyses")
    async def get_analyses(
        _: Annotated[Identity, Depends(require_platform)],
    ) -> dict[str, object]:
        return {
            "analyses": [
                {**row.__dict__, "thresholds": [t.__dict__ for t in row.thresholds]}
                for row in catalog.analyses()
            ]
        }

    return app
