"""The app. Six read-only PLATFORM routes, one reader engine, no write path.

WHAT ``/readyz`` PROVES, and it is deliberately more than "the process is up": it opens a real
PLATFORM session, which exercises dis-rls's first-use guard — the target database is the expected
one and the role is NOSUPERUSER NOBYPASSRLS. A revision pointed at the wrong database, or holding
a role that can bypass RLS, fails readiness instead of serving a console that silently shows the
wrong tenants or trusts a credential that can see everything.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated
from uuid import UUID

from fastapi import Depends, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from dis_core.logging import configure_logging, get_logger
from dis_rls import create_rls_engine, rls_platform_session
from synapse_ui_server import catalog, reads
from synapse_ui_server.auth import Auth0Verifier, AuthError, Identity, require_platform
from synapse_ui_server.config import Config, load_config

_log = get_logger("synapse-ui-server")

_REASON_STATUS = {"missing": 401, "invalid": 401, "forbidden": 403}


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    config: Config = app.state.config
    # ONE engine, from the reader DSN. There is no writer engine because there is no writer DSN;
    # see the package docstring for why that is a property rather than an omission.
    app.state.engine = create_rls_engine(config.reader_url)
    app.state.verifier = getattr(app.state, "verifier", None) or Auth0Verifier(
        jwks_url=config.jwks_url, issuer=config.jwt_issuer, audience=config.jwt_audience
    )
    _log.info("synapse-ui-server ready", extra={"read_only": True, "writer_configured": False})
    try:
        yield
    finally:
        await app.state.engine.dispose()


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
