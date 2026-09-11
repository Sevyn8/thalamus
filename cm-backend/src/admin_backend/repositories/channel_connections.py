"""Reads and the upsert for ``axon.channel_connections``.

CUSTOMER MASTER WRITES A TABLE IN THE AXON SCHEMA, AND THAT IS DELIBERATE RATHER THAN A LEAK.
The tenant administrator types the credential into CM, because CM is where tenant configuration
and the permission model live. The row it produces belongs to Axon's plane, and both live in the
SAME DATABASE: the Cloud SQL instance carries exactly one application database, and its Terraform
module says so in as many words ("The single shared database... BOTH apps must point their
DATABASE_URL at this one db"). So CM reaches the table with a grant rather than with an HTTP call
to a service that has no HTTP surface.

=================================================================================================
EVERY QUERY HERE RUNS UNDER get_tenant_session_dep, AND THE POSTURE IS THE WHOLE ACCESS CONTROL
=================================================================================================
That dependency is the only path that sets ``app.tenant_id`` and ``app.user_type``, and it sets
them from the verified token and nothing else. The table is FORCE ROW LEVEL SECURITY with the
PLATFORM branch in USING only:

  TENANT session   reads and writes its own row. The WITH CHECK pins the write to the session's
                   tenant, so a tenant cannot write a row naming another tenant even if the
                   handler passed one.
  PLATFORM session reads EVERY tenant's row through the USING branch, and cannot write at all
                   (WITH CHECK has no PLATFORM branch, by design).

THE SILENT FAILURE THIS TABLE INVITES. With the GUCs unset a SELECT here returns ZERO ROWS and
raises nothing, which is indistinguishable from "no tenant has configured a channel". That has
bitten this estate seven times in three days, once on a DELETE as the table owner. Every read
below is therefore reached only through the dependency, and the platform read's test asserts that
a PLATFORM session sees ANOTHER tenant's row rather than merely that the query succeeded.

=================================================================================================
THE UPSERT USES ON CONFLICT, AND WHY THAT IS SAFE HERE IS NOT A GENERAL PERMISSION
=================================================================================================
``channel_connections``' DDL carries a warning naming
``infra/db-setup/sql/06_axon_sender_grant.sql``: ON CONFLICT reads the ARBITER INDEX, which is a
SELECT privilege on the table. That grant gave the writing role INSERT and no SELECT, so every
enable failed with `permission denied` behind a green apply.

That role was ``axon_sender``, which deliberately holds no SELECT anywhere and still does. THIS
role is ``user_admin_backend``, which needs SELECT on this table anyway for both reads above, so
the arbiter read costs nothing extra and the grant lands in the same file and the same commit as
this statement: ``infra/db-setup/sql/09_cm_channel_connections_grant.sql`` grants SELECT, INSERT
and UPDATE together. No DELETE: a tenant disconnecting a channel is a status flip, and a row that
can be deleted is a credential reference that can vanish without a trace.

Do not read this as "ON CONFLICT is fine in general"; read it as "this role holds the SELECT that
ON CONFLICT needs here, and that was checked".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

__all__ = ["ChannelConnectionRow", "ChannelConnectionsRepo"]


@dataclass(frozen=True)
class ChannelConnectionRow:
    """One connection, as every read surface sees it.

    NO CREDENTIAL FIELD, AND THAT IS THE POINT. ``secret_ref`` is the secret's NAME; the value is
    in Secret Manager and this process cannot read it back (the IAM role omits versions.access).
    A read surface that cannot obtain the value cannot leak it, whatever a future handler does.
    """

    tenant_id: UUID
    channel: str
    provider: str
    status: str
    sending_identity: str | None
    secret_ref: str | None
    connected_at: datetime | None
    disabled_at: datetime | None
    created_at: datetime
    updated_at: datetime


# Every column this module ever projects. Written once so the three statements below cannot
# drift into selecting different shapes for the same dataclass.
_COLUMNS = (
    "tenant_id, channel, provider, status, sending_identity, secret_ref, "
    "connected_at, disabled_at, created_at, updated_at"
)


def _row(record: object) -> ChannelConnectionRow:
    r = record  # SQLAlchemy Row; attribute access below is checked by the tests
    return ChannelConnectionRow(
        tenant_id=UUID(str(r.tenant_id)),  # type: ignore[attr-defined]
        channel=str(r.channel),  # type: ignore[attr-defined]
        provider=str(r.provider),  # type: ignore[attr-defined]
        status=str(r.status),  # type: ignore[attr-defined]
        sending_identity=r.sending_identity,  # type: ignore[attr-defined]
        secret_ref=r.secret_ref,  # type: ignore[attr-defined]
        connected_at=r.connected_at,  # type: ignore[attr-defined]
        disabled_at=r.disabled_at,  # type: ignore[attr-defined]
        created_at=r.created_at,  # type: ignore[attr-defined]
        updated_at=r.updated_at,  # type: ignore[attr-defined]
    )


class ChannelConnectionsRepo:
    """Stateless singleton, same shape as every other Repo here: methods take the session."""

    async def list_for_session_tenant(self, session: AsyncSession) -> list[ChannelConnectionRow]:
        """Every connection visible to this session.

        UNDER A TENANT SESSION this is that tenant's rows, by the policy's equality branch. It
        takes no tenant_id argument on purpose: a caller that could pass one could pass the wrong
        one, and the token is the only trustworthy source (AI-MT-02).
        """
        result = await session.execute(
            text(f"SELECT {_COLUMNS} FROM axon.channel_connections ORDER BY channel")
        )
        return [_row(r) for r in result.all()]

    async def list_all_tenants(self, session: AsyncSession) -> list[ChannelConnectionRow]:
        """Every tenant's connection state, for the platform operator surface.

        SESSION POSTURE: PLATFORM. The policy's USING branch is what widens this beyond one
        tenant; under any other posture it returns zero rows and raises nothing. The handler is
        gated ``audience="PLATFORM"`` so the posture and the permission cannot disagree.

        Ordered by tenant then channel so the console's rows are stable across reloads.
        """
        result = await session.execute(
            text(f"SELECT {_COLUMNS} FROM axon.channel_connections ORDER BY tenant_id, channel")
        )
        return [_row(r) for r in result.all()]

    async def upsert(
        self,
        session: AsyncSession,
        *,
        tenant_id: UUID,
        channel: str,
        provider: str,
        sending_identity: str | None,
        secret_ref: str,
    ) -> ChannelConnectionRow:
        """Create or replace this tenant's connection for one channel.

        WRITTEN INTO THE OPEN REQUEST TRANSACTION AND NOT COMMITTED HERE. The handler orders the
        Secret Manager write AFTER this call precisely so that a vault failure rolls this back;
        committing here would defeat that. See the router for the full ordering argument.

        STATUS IS FORCED TO 'pending' AND NEVER ADVANCED. The DDL permits pending, connected and
        disabled, and its comment records that only pending is reachable: `connected` means a send
        was ACCEPTED on this channel, and no adapter beyond email exists to accept one. Writing
        `connected` here would be the surface claiming a delivery capability the platform does not
        have.

        ON CONFLICT: see the module docstring for why the arbiter read is affordable to this role
        and was not to 5e's.
        """
        result = await session.execute(
            text(
                f"""
                INSERT INTO axon.channel_connections (
                    tenant_id, channel, provider, status,
                    sending_identity, secret_ref,
                    created_at, updated_at
                ) VALUES (
                    :tenant_id, :channel, :provider, 'pending',
                    :sending_identity, :secret_ref,
                    now(), now()
                )
                ON CONFLICT ON CONSTRAINT pk_channel_connections DO UPDATE SET
                    provider         = EXCLUDED.provider,
                    status           = 'pending',
                    sending_identity = EXCLUDED.sending_identity,
                    secret_ref       = EXCLUDED.secret_ref,
                    connected_at     = NULL,
                    disabled_at      = NULL,
                    updated_at       = now()
                RETURNING {_COLUMNS}
                """
            ),
            {
                "tenant_id": str(tenant_id),
                "channel": channel,
                "provider": provider,
                "sending_identity": sending_identity,
                "secret_ref": secret_ref,
            },
        )
        record = result.first()
        if record is None:  # pragma: no cover - RETURNING on an accepted write always yields one
            raise RuntimeError(
                "the channel_connections upsert returned no row. Under this table's policy a "
                "write that the WITH CHECK refused raises rather than returning nothing, so this "
                "means the statement changed shape."
            )
        # connected_at and disabled_at are cleared explicitly rather than left alone: the DDL
        # pairs each to its status by CHECK, and re-entering a credential returns the connection
        # to pending, so a stale connected_at from a previous stint would violate the pair.
        return _row(record)
