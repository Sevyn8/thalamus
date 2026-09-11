"""The tenant channel surface, end to end, against a real Postgres with the real policy.

=================================================================================================
THE axon SCHEMA IS CREATED HERE FROM AXON'S OWN DDL TEXT, AND NOT COPIED
=================================================================================================
cm-backend's integration suite runs against the local CM database, which carries ``core`` and
nothing else; ``axon`` lives in a different local container. In STAGING there is one database and
CM reaches the table with a grant, which is what makes this whole design work. Locally the schema
has to be created for the tests to be real.

The fixture below EXECUTES THE channel_connections PORTION OF
``axon/schemas/postgres/channels.sql`` verbatim rather than restating the table. A second CREATE
TABLE in this file would be a second definition of a table CM does not own, free to drift from
the one staging actually has, and every RLS assertion below would then be proving something about
CM's copy instead of about Axon's table. The slice stops before ``channel_templates`` because that
table needs btree_gist and the foreign key needs ``axon.tenant_deliveries``, neither of which this
slice touches; the fixture asserts it cut where it meant to.

WHAT THIS BUYS: the policy under test is the real FORCE ROW LEVEL SECURITY policy, so the
platform-read test below is genuinely proving that a PLATFORM session crosses tenants and a
TENANT session does not.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterator
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text

from admin_backend.config import Settings
from admin_backend.main import create_app

_CHANNELS_DDL = (
    Path(__file__).resolve().parents[3] / "axon" / "schemas" / "postgres" / "channels.sql"
)


def _channel_connections_ddl() -> str:
    """Axon's own text for the one table this slice writes. See the module docstring."""
    source = _CHANNELS_DDL.read_text(encoding="utf-8")
    start = source.index("CREATE TABLE IF NOT EXISTS axon.channel_connections")
    end = source.index("CREATE TABLE IF NOT EXISTS axon.channel_templates")
    return source[start:end]


@pytest.fixture(scope="module", autouse=True)
def axon_channel_connections(request: pytest.FixtureRequest) -> None:
    """Create ``axon.channel_connections`` in the CM test database, from Axon's DDL.

    Module-scoped and idempotent: the DDL is CREATE TABLE IF NOT EXISTS and DROP-then-CREATE for
    its policy, so re-running a suite does not fail. Deliberately NOT torn down; a developer's
    database keeping an empty axon schema mirrors staging rather than diverging from it.
    """
    import psycopg

    from admin_backend.config import get_settings

    ddl = _channel_connections_ddl()
    # THE VACUITY GUARD ON THE SLICE. If the DDL is reorganised so the markers move, this would
    # otherwise execute a fragment and every test below would fail confusingly at query time.
    assert "CONSTRAINT pk_channel_connections PRIMARY KEY (tenant_id, channel)" in ddl
    assert "FORCE ROW LEVEL SECURITY" in ddl
    assert "CREATE POLICY channel_connections_tenant_isolation" in ddl
    assert "channel_templates" not in ddl.split("-- axon.channel_templates")[0]

    dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("CREATE SCHEMA IF NOT EXISTS axon")
        conn.execute(ddl)


@pytest.fixture(scope="module", autouse=True)
def channels_permissions_present(axon_channel_connections: None) -> None:
    """Ensure the three ADMIN.CHANNELS tuples exist in the local catalogue.

    =============================================================================================
    THIS FIXTURE EXISTS BECAUSE OF A REAL OPERATIONAL GAP, NOT BECAUSE OF A TEST INCONVENIENCE
    =============================================================================================
    Migration b7e3c95a1d84 INSERTS the three CHANNELS permissions. It has been applied here: the
    local ``core.alembic_version`` reads b7e3c95a1d84. And the rows are gone: ``core.permissions``
    holds 37 rows and none of them is a CHANNELS tuple.

    The cause is that ``scripts/seed_dev_data --reset`` TRUNCATEs ``core.permissions`` and
    reloads the workbook, which does not contain these three rows. Alembic will never restore
    them, because the revision that inserts them is already stamped. So any environment that has
    been reseeded since 2026-08-12 has silently lost them, and STAGING IS ONE ``--reset`` AWAY
    FROM THE SAME STATE, which would take the tenant channel surface down with it.

    The durable fix is to add the three rows to ``data/ithina_dev_seed_data.xlsx`` and move
    test_seed_loader's expected count from 37 to 40. That is a deliberate change to what a reseed
    produces and it is reported rather than smuggled in here.

    This fixture is idempotent and inserts nothing that the migration would not have.
    """
    import psycopg

    from admin_backend.config import get_settings

    dsn = get_settings().database_url.replace("postgresql+psycopg://", "postgresql://")
    with psycopg.connect(dsn, autocommit=True) as conn:
        conn.execute("SELECT set_config('app.user_type','PLATFORM',false)")
        for action, scope in (("VIEW", "TENANT"), ("CONFIGURE", "TENANT"), ("VIEW", "GLOBAL")):
            conn.execute(
                """
                INSERT INTO core.permissions (module, resource, action, scope, code, description)
                VALUES (
                    CAST('ADMIN' AS core.module_code_enum),
                    CAST('CHANNELS' AS core.resource_enum),
                    CAST(%s AS core.action_enum),
                    CAST(%s AS core.permission_scope_enum),
                    %s, %s
                )
                ON CONFLICT DO NOTHING
                """,
                (
                    action,
                    scope,
                    f"ADMIN.CHANNELS.{action}.{scope}",
                    "Tenant sending channels (restored by the channels test fixture)",
                ),
            )
        # SUPER_ADMIN's VIEW.GLOBAL grant was wiped by the same reseed. Restored here for the
        # same reason and with the same idempotency. PLATFORM-audience role plus GLOBAL-scope
        # permission is exactly what the audience-scope trigger permits.
        conn.execute(
            """
            INSERT INTO core.role_permissions (role_id, permission_id)
            SELECT r.id, p.id
            FROM core.roles r
            CROSS JOIN core.permissions p
            WHERE r.code = 'SUPER_ADMIN'
              AND p.code = 'ADMIN.CHANNELS.VIEW.GLOBAL'
            ON CONFLICT DO NOTHING
            """
        )


class _FakeWriter:
    """A vault that records rather than calls. The real one is never reached in tests."""

    def __init__(self, *, fail_write: bool = False, fail_prune: bool = False) -> None:
        self.writes: list[tuple[str, bytes]] = []
        self.prunes: list[tuple[str, str]] = []
        self._fail_write = fail_write
        self._fail_prune = fail_prune

    def write(self, secret_id: str, payload: bytes) -> str:
        self.writes.append((secret_id, payload))
        if self._fail_write:
            raise RuntimeError("vault is down")
        return f"{secret_id}/versions/1"

    def prune(self, secret_id: str, keep_version_name: str) -> int:
        self.prunes.append((secret_id, keep_version_name))
        if self._fail_prune:
            raise RuntimeError("prune is down")
        return 1


@pytest.fixture
def make_client(settings: Settings, engine: Any, session_factory: Any):  # type: ignore[no-untyped-def]
    """A TestClient whose app.state carries a fake vault writer."""

    def build(writer: object | None) -> Iterator[TestClient]:
        from admin_backend.auth.stub import StubAuthClient

        app_obj: FastAPI = create_app()
        app_obj.state.settings = settings
        app_obj.state.engine = engine
        app_obj.state.session_factory = session_factory
        app_obj.state.auth_client = StubAuthClient(settings)
        app_obj.state.channel_secret_writer = writer
        return TestClient(app_obj)  # type: ignore[return-value]

    return build


def _auth(jwt: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {jwt}"}


def _body(channel: str = "whatsapp") -> dict[str, Any]:
    return {
        "channel": channel,
        "provider": "sinch",
        "sending_identity": "+15550001111",
        "credential": [
            {"key": "client_id", "value": "cid-123"},
            {"key": "username", "value": "user-abc"},
            {"key": "password", "value": "hunter2-the-secret"},
        ],
    }


async def _row_count(session_factory: Any, tenant_id: UUID) -> int:
    """Count rows as the OWNER under an explicit PLATFORM posture.

    THE POSTURE IS STATED BECAUSE WITHOUT IT THIS COUNTS ZERO AND RAISES NOTHING. The table is
    FORCE RLS, so the owner is subject to the policy; a bare count here would report 0 for a row
    that exists and the test would pass while asserting the opposite of what it means.
    """
    async with session_factory() as s:
        await s.execute(text("SELECT set_config('app.user_type','PLATFORM',true)"))
        await s.execute(text("SELECT set_config('app.tenant_id','',true)"))
        result = await s.execute(
            text("SELECT count(*) FROM axon.channel_connections WHERE tenant_id = :t"),
            {"t": str(tenant_id)},
        )
        return int(result.scalar_one())


# ---------------------------------------------------------------------------
# The tenant's own surface
# ---------------------------------------------------------------------------


async def test_c1_tenant_configures_a_channel_and_the_row_and_secret_both_land(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any, session_factory: Any
) -> None:
    """THE HAPPY PATH, ASSERTED ON BOTH SIDES OF THE NON-ATOMIC PAIR.

    A response alone would not prove the row committed, and a row alone would not prove the
    credential reached the vault. This asserts the row, the secret name, and that the name written
    to the vault is the SAME name recorded on the row, which is the join the reader depends on.
    """
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "CONFIGURE", "TENANT")]
    )
    writer = _FakeWriter()
    client = make_client(writer)

    response = client.put("/api/v1/channels", json=_body(), headers=_auth(jwt))

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["channel"] == "whatsapp"
    assert payload["status"] == "pending"
    assert payload["secret_ref"] == f"axon-channel-{tenant.id}-whatsapp"
    assert await _row_count(session_factory, tenant.id) == 1
    assert len(writer.writes) == 1
    assert writer.writes[0][0] == payload["secret_ref"], (
        "the name written to the vault differs from the name recorded on the row. The reader "
        "resolves the credential through secret_ref, so this pair disagreeing is a credential "
        "nothing can find."
    )


async def test_c2_the_response_never_carries_the_credential(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any
) -> None:
    """LOAD-BEARING. The single promise this whole surface makes.

    Asserted on the RAW BODY rather than on parsed fields, because a leak would most likely
    arrive as a field nobody thought to check rather than as one of the fields asserted above.
    """
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "CONFIGURE", "TENANT")]
    )
    client = make_client(_FakeWriter())

    response = client.put("/api/v1/channels", json=_body(), headers=_auth(jwt))
    assert response.status_code == 200

    raw = response.text
    for secret in ("hunter2-the-secret", "cid-123", "user-abc"):
        assert secret not in raw, f"the response body contains the credential value {secret!r}"
    assert "credential" not in response.json()


async def test_c3_a_vault_failure_leaves_no_row(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any, session_factory: Any
) -> None:
    """LOAD-BEARING. THE ORDERING, PROVED RATHER THAN COMMENTED.

    The row is written into the open transaction BEFORE the vault call so that a vault failure
    rolls it back. If the handler ever commits first, or catches the vault error, this test fails
    and the surface starts recording connections whose credential was never stored, which reads as
    configured and can never send.
    """
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "CONFIGURE", "TENANT")]
    )
    client = make_client(_FakeWriter(fail_write=True))

    with pytest.raises(RuntimeError):
        client.put("/api/v1/channels", json=_body(), headers=_auth(jwt))

    assert await _row_count(session_factory, tenant.id) == 0, (
        "a row survived a failed vault write. The connection would read as configured while no "
        "credential exists, which is worse than the failure the tenant would have retried."
    )


async def test_c4_a_prune_failure_does_not_lose_a_successful_save(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any, session_factory: Any
) -> None:
    """The prune is housekeeping and its failure must not undo a stored credential. The inverse
    of C3, and the reason the two calls are not in one try block."""
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "CONFIGURE", "TENANT")]
    )
    client = make_client(_FakeWriter(fail_prune=True))

    response = client.put("/api/v1/channels", json=_body(), headers=_auth(jwt))

    assert response.status_code == 200
    assert await _row_count(session_factory, tenant.id) == 1


async def test_c5_the_prune_is_actually_called_with_the_version_just_written(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any
) -> None:
    """A PRUNE THAT SILENTLY DOES NOTHING IS INDISTINGUISHABLE FROM ONE THAT WORKS.

    Without this, the writer could hold versions.destroy and never call it, and every superseded
    credential a tenant ever entered would stay live in the vault behind a healthy-looking save.
    That is the exact trap dis-ui-server's tokenVaultWriter comment records.
    """
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "CONFIGURE", "TENANT")]
    )
    writer = _FakeWriter()
    client = make_client(writer)

    client.put("/api/v1/channels", json=_body(), headers=_auth(jwt))

    assert len(writer.prunes) == 1, "the prune was never called"
    secret_id, kept = writer.prunes[0]
    assert secret_id == f"axon-channel-{tenant.id}-whatsapp"
    assert kept == writer.writes[0][0] + "/versions/1", (
        "the prune was asked to keep a version other than the one just written, which would "
        "destroy the credential the tenant just entered"
    )


async def test_c6_reconfiguring_replaces_rather_than_duplicating(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any, session_factory: Any
) -> None:
    """THE UPSERT'S ARBITER, EXERCISED. ON CONFLICT reads the primary-key index, which requires
    a SELECT privilege. CM holds SELECT for its two reads, so the second save updates rather
    than raising a duplicate-key error."""
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "CONFIGURE", "TENANT")]
    )
    client = make_client(_FakeWriter())

    client.put("/api/v1/channels", json=_body(), headers=_auth(jwt))
    second = _body()
    second["sending_identity"] = "+15559999999"
    response = client.put("/api/v1/channels", json=second, headers=_auth(jwt))

    assert response.status_code == 200
    assert response.json()["sending_identity"] == "+15559999999"
    assert await _row_count(session_factory, tenant.id) == 1


async def test_c7_a_tenant_reads_its_own_channels(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any
) -> None:
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id,
        with_grants=[
            ("ADMIN", "CHANNELS", "CONFIGURE", "TENANT"),
            ("ADMIN", "CHANNELS", "VIEW", "TENANT"),
        ],
    )
    client = make_client(_FakeWriter())
    client.put("/api/v1/channels", json=_body(), headers=_auth(jwt))

    response = client.get("/api/v1/channels", headers=_auth(jwt))

    assert response.status_code == 200
    items = response.json()["items"]
    assert [i["channel"] for i in items] == ["whatsapp"]
    assert "credential" not in items[0]


@pytest.mark.parametrize(
    ("bad", "why"),
    [
        ({"credential": []}, "empty credential set"),
        (
            {
                "credential": [
                    {"key": "a", "value": "1"},
                    {"key": "a", "value": "2"},
                ]
            },
            "duplicate keys silently drop one of the tenant's values",
        ),
        ({"credential": [{"key": "has space", "value": "1"}]}, "illegal key charset"),
        ({"credential": [{"key": "a", "value": ""}]}, "empty value"),
        ({"channel": "voice"}, "channel outside the ledger's vocabulary"),
    ],
)
async def test_c8_malformed_credentials_are_refused(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any, bad: Any, why: str
) -> None:
    """SHAPE ONLY, NEVER SEMANTICS. Nothing here knows what a Sinch credential looks like; these
    refuse sets that would lose a value or produce an unresolvable name."""
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "CONFIGURE", "TENANT")]
    )
    client = make_client(_FakeWriter())
    payload = {**_body(), **bad}

    response = client.put("/api/v1/channels", json=payload, headers=_auth(jwt))

    assert response.status_code == 422, f"{why} was accepted"


async def test_c9_an_unconfigured_deployment_refuses_rather_than_pretending(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any, session_factory: Any
) -> None:
    """No vault configured means no credential can be stored. A 503 that says so is the only
    honest answer; writing the row anyway would record a connection with nothing behind it."""
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "CONFIGURE", "TENANT")]
    )
    client = make_client(None)

    response = client.put("/api/v1/channels", json=_body(), headers=_auth(jwt))

    assert response.status_code == 503
    assert response.json()["code"] == "CHANNELS_UNAVAILABLE"
    assert await _row_count(session_factory, tenant.id) == 0


# ---------------------------------------------------------------------------
# The operator surface, and the two audiences that must not cross
# ---------------------------------------------------------------------------


async def test_p1_a_platform_session_sees_another_tenants_connection(
    make_client: Any,
    make_tenant: Any,
    tenant_owner_jwt_factory: Any,
    super_admin_jwt: str,
) -> None:
    """LOAD-BEARING, AND IT ASSERTS THE CROSSING RATHER THAN THE QUERY.

    ``axon.channel_connections`` is FORCE RLS with the PLATFORM branch in USING only. A read under
    the wrong posture returns ZERO ROWS and raises nothing, which is indistinguishable from "no
    tenant has configured a channel"; that failure has bitten this estate seven times in three
    days. So this writes a row as TENANT A and asserts a PLATFORM caller can see THAT row. A test
    that merely asserted a 200 would pass against a completely broken posture.
    """
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    tenant_jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "CONFIGURE", "TENANT")]
    )
    client = make_client(_FakeWriter())
    client.put("/api/v1/channels", json=_body(), headers=_auth(tenant_jwt))

    response = client.get("/api/v1/channels/platform", headers=_auth(super_admin_jwt))

    assert response.status_code == 200, response.text
    mine = [i for i in response.json()["items"] if i["tenant_id"] == str(tenant.id)]
    assert len(mine) == 1, (
        "a PLATFORM session could not see a tenant's connection. Either the posture is wrong or "
        "the policy's USING branch changed; both look like an empty fleet."
    )
    assert mine[0]["secret_ref"] == f"axon-channel-{tenant.id}-whatsapp"
    assert "credential" not in mine[0]


async def test_p2_a_tenant_caller_is_refused_at_the_platform_route(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any
) -> None:
    """The audience pin refuses a TENANT caller before any permission is resolved.

    THIS TEST WAS FIRST WRITTEN TO GRANT THE CALLER ADMIN.CHANNELS.VIEW.GLOBAL and assert the
    audience gate refused them anyway. The database refused to set that up: the
    trigger ``enforce_role_audience_scope_coherence`` raises on any attempt to give a
    TENANT-audience role a GLOBAL-scope permission, and ``enforce_tenant_role_audience`` stops a
    tenant user holding a PLATFORM-audience role. So a TENANT caller holding a GLOBAL grant IS
    NOT A REACHABLE STATE, and a test asserting behaviour in it would have been asserting
    something about a fixture rather than about the product.

    What is reachable, and what this asserts, is a tenant administrator with ordinary tenant
    grants reaching the operator URL. The audience check fires first and names the reason. The
    ``audience="PLATFORM"`` pin is therefore a second layer over a structural guarantee, which is
    worth keeping: it turns a refusal that would otherwise depend on two triggers and a policy
    into one that says why.
    """
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "CHANNELS", "VIEW", "TENANT")]
    )
    client = make_client(_FakeWriter())

    response = client.get("/api/v1/channels/platform", headers=_auth(jwt))

    assert response.status_code == 403
    assert response.json()["code"] == "PLATFORM_AUDIENCE_REQUIRED", (
        "the refusal did not come from the audience gate. If it came from has_permission the "
        "ordering changed, and a caller would be told they lack a permission rather than that "
        "the route is not theirs."
    )


async def test_p3_a_platform_caller_cannot_configure_a_tenants_channel(
    make_client: Any, super_admin_jwt: str
) -> None:
    """LOAD-BEARING, AND IT IS THE STANDING RULE RATHER THAN A PERMISSION DETAIL.

    Sevyn8 never holds or types another company's credential. SUPER_ADMIN holds
    ADMIN.CHANNELS.VIEW.GLOBAL and still must not write one. The row's own WITH CHECK would refuse
    a PLATFORM write anyway, but a refusal at the gate names the reason instead of surfacing as a
    policy violation nobody can read.
    """
    client = make_client(_FakeWriter())

    response = client.put("/api/v1/channels", json=_body(), headers=_auth(super_admin_jwt))

    assert response.status_code == 403


async def test_p4_a_tenant_without_the_grant_is_refused(
    make_client: Any, make_tenant: Any, tenant_owner_jwt_factory: Any
) -> None:
    """The gate is the boundary; /me/permissions only decides what the browser draws."""
    tenant = await make_tenant(name=f"chan-{uuid4().hex[:8]}", with_root=True)
    jwt = await tenant_owner_jwt_factory(
        tenant.id, with_grants=[("ADMIN", "USERS", "VIEW", "TENANT")]
    )
    client = make_client(_FakeWriter())

    assert client.get("/api/v1/channels", headers=_auth(jwt)).status_code == 403
    assert (
        client.put("/api/v1/channels", json=_body(), headers=_auth(jwt)).status_code == 403
    )


async def test_p5_no_token_is_refused(make_client: Any) -> None:
    client = make_client(_FakeWriter())
    assert client.get("/api/v1/channels").status_code == 401
    assert client.get("/api/v1/channels/platform").status_code == 401
