"""This service writes TWO tables through TWO credentials, and these are what keep it there.

IT WAS READ-ONLY UNTIL SLICE 5d, and every write path since has been the deliberate act this file
demanded. The original header said "Slice 8b needs a writer for provisioning. It must add one
DELIBERATELY, which is what these tests turn into a visible act rather than a discovery that it
was already wired." The mechanism has now worked twice: 5d added the alert lifecycle and 5e added
provisioning, and each meant editing this file, in the open, with the reasoning attached.

WHAT THE CONTRACT IS NOW. Not "cannot write", and not a blanket "the service may write" either.
It is an enumeration:

    lifecycle.py   INSERT on synapse.action_events, as synapse_lifecycle    (5d)
    provision.py   INSERT on synapse.provision, as synapse_provisioner      (5e)

TWO NAMES, NOT A PERMISSION. The counted tests below go from "exactly one" to "exactly two" and
each exemption is spelled out by filename, so a THIRD write surface fails here and has to be
argued for. Widening these into "any module may write" would be the real weakening, and it is the
easy edit to make when a test goes red, which is why the reasoning sits above the assertion.

THE PROPERTIES, AND ONLY THE LAST IS PYTHON:

  - THE GRANTS. synapse_lifecycle holds INSERT on synapse.action_events and nothing else
    (migration 0006). synapse_provisioner holds INSERT on synapse.provision plus SELECT on
    identity_mirror.tenants and canonical.store_sku_current_position, which its enablement
    pre-flight cannot run without, and nothing else
    (infra/db-setup/sql/05_synapse_provisioner_grant.sql). NEITHER HOLDS UPDATE ANYWHERE, so
    neither can edit or undo what it wrote. Postgres refuses everything else whatever this code
    says.
  - THE TRIGGERS. action_events is append-only and binds the owner too; provision refuses an
    unresolvable timezone the same way.
  - THE POLICIES. Both tables are FORCE ROW LEVEL SECURITY with a WITH CHECK on app.tenant_id,
    so both writes must open a TENANT-scoped session and a PLATFORM one can write neither.
  - THE MODULE BOUNDARY. Exactly two files here may contain a write, which is what
    test_no_module_outside_the_two_write_modules_issues_a_write asserts.

SYNAPSE_WRITER_URL IS STILL REFUSED, and going from one write credential to two is the argument
FOR that rather than against it. Each of these is one verb on one table; the writer is the
ORCHESTRATOR's identity and can append to the action log itself, so a console holding it would
make every row ambiguous about whether a human or the 04:00 sweep produced it.

THE ARGUMENT, one layer up from slice 5. ``synapse_writer`` holds INSERT and no SELECT, so
"resolvers never write" is a runtime fact rather than a grep. The same reasoning applies here: a
service that merely CHOOSES not to write outside two files is equivalent in behaviour and not in
property. A credential that cannot do a thing cannot be made to do it by a bug, a merge, or a
contributor in a hurry.

"""

from __future__ import annotations

import re
from dataclasses import fields
from pathlib import Path

import pytest
import synapse_ui_server.reads as reads_module
from synapse_ui_server.config import Config, load_config


def test_the_config_has_no_orchestrator_writer_field() -> None:
    """A field that does not exist cannot be populated by a stray environment variable.

    ``lifecycle_url`` and ``provision_url`` exist now; ``writer_url`` still must not. All three
    are different credentials with different blast radii, and the console is entitled to the two
    small ones and never to the orchestrator's.
    """
    names = {field.name for field in fields(Config)}
    assert "writer_url" not in names
    assert "lifecycle_url" in names, "the lifecycle DSN is required; slice 5d writes with it"
    assert "provision_url" in names, "the provisioner DSN is required; slice 5e writes with it"


def test_a_writer_dsn_in_the_environment_is_a_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOT A WARNING. A writer DSN present here means somebody wired one expecting it to be
    used, and nothing in this service can. Failing beats a live credential sitting unused in a
    revision's environment, reachable by anything that can read the config."""
    _base_env(monkeypatch)
    monkeypatch.setenv("SYNAPSE_WRITER_URL", "postgresql+psycopg://w@localhost/db")

    with pytest.raises(RuntimeError, match="ORCHESTRATOR"):
        load_config()


def test_the_config_loads_with_both_write_dsns_and_no_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline. Without it the test above would pass against a loader that always raised."""
    _base_env(monkeypatch)
    config = load_config()
    assert config.reader_url.endswith("/db")
    assert config.lifecycle_url.endswith("/db")
    assert config.provision_url.endswith("/db")


@pytest.mark.parametrize(
    "name",
    [
        "SYNAPSE_LIFECYCLE_URL",
        "SYNAPSE_PROVISION_URL",
        "CM_API_BASE_URL",
        # AXON's four (slice 1). Covered by the SAME test as the write DSNs deliberately: this
        # test is the 5d guard, and 5d was an env var the module never wired sitting dead in
        # staging for two days behind a green apply. A delivery plane that silently carries
        # nothing is the same failure with a different blast radius.
        "AXON_SENDER_URL",
        "AXON_SENDGRID_API_KEY",
        "AXON_SENDGRID_FROM_EMAIL",
        "AXON_PLATFORM_ONCALL_EMAIL",
    ],
)
def test_every_write_path_variable_is_required(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """A service that cannot write is not the goal any more — a service that SILENTLY cannot
    write is worse than one that refuses to start. Every POST on the affected path would 500 at
    runtime instead, on a revision whose deploy was green.

    CM_API_BASE_URL IS IN THIS LIST AND IT IS NOT A CREDENTIAL. Without it the provisioning gate
    cannot ask Customer Master whether the caller may configure a tenant, and because that gate
    fails closed the endpoint would deny every request. A service that cannot evaluate its own
    authorization must not start: the failure would otherwise read as "nobody has the permission"
    rather than "the service is misconfigured".
    """
    _base_env(monkeypatch)
    monkeypatch.delenv(name, raising=False)
    with pytest.raises(RuntimeError, match=name):
        load_config()


def test_a_trailing_slash_on_the_cm_origin_is_stripped(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hand-written into terraform, so it will eventually arrive with one. A doubled slash makes
    the can-do URL 404, and a 404 from a fail-closed gate denies every enable while reading like
    a missing endpoint rather than a typo."""
    _base_env(monkeypatch)
    monkeypatch.setenv("CM_API_BASE_URL", "https://cm.example.run.app/")
    assert load_config().cm_api_base_url == "https://cm.example.run.app"


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYNAPSE_WRITER_URL", raising=False)
    monkeypatch.setenv("SYNAPSE_READER_URL", "postgresql+psycopg://r@localhost/db")
    monkeypatch.setenv("SYNAPSE_LIFECYCLE_URL", "postgresql+psycopg://l@localhost/db")
    monkeypatch.setenv("SYNAPSE_PROVISION_URL", "postgresql+psycopg://p@localhost/db")
    monkeypatch.setenv("CM_API_BASE_URL", "https://cm.example.run.app")
    monkeypatch.setenv("SYNAPSE_JWT_ISSUER", "https://example.auth0.com/")
    monkeypatch.setenv("SYNAPSE_JWT_AUDIENCE", "https://api.example")
    # AXON (slice 1). Four more required variables, and they are here rather than in a separate
    # fixture because load_config reports EVERY missing name at once: a partial base env would
    # make every test below fail on Axon's names instead of on the thing it is testing.
    monkeypatch.setenv("AXON_SENDER_URL", "postgresql+psycopg://a@localhost/db")
    monkeypatch.setenv("AXON_SENDGRID_API_KEY", "test-key")
    monkeypatch.setenv("AXON_SENDGRID_FROM_EMAIL", "noreply@example.invalid")
    monkeypatch.setenv("AXON_PLATFORM_ONCALL_EMAIL", "oncall@example.invalid")


def test_missing_variables_are_reported_together(monkeypatch: pytest.MonkeyPatch) -> None:
    """All at once, not the first. An operator fixing one and redeploying to find the next is
    three deploys where one would do."""
    for name in ("SYNAPSE_READER_URL", "SYNAPSE_JWT_ISSUER", "SYNAPSE_JWT_AUDIENCE"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("SYNAPSE_WRITER_URL", raising=False)

    with pytest.raises(RuntimeError) as caught:
        load_config()
    message = str(caught.value)
    for name in ("SYNAPSE_READER_URL", "SYNAPSE_JWT_ISSUER", "SYNAPSE_JWT_AUDIENCE"):
        assert name in message


# THE EXEMPTION LIST, AS DATA. Two files, each named, each with its credential and its table
# beside it. A third entry is the diff that has to be argued for, and having it be a list rather
# than a chain of `if path.name == ...` is what makes adding one visible in a review.
_WRITE_MODULES = {
    "lifecycle.py": "synapse.action_events as synapse_lifecycle (5d)",
    "provision.py": "synapse.provision as synapse_provisioner (5e)",
}


def test_no_module_outside_the_two_write_modules_issues_a_write() -> None:
    """GREPPED, because the claim is about every statement this service can execute.

    RESHAPED TWICE, NOT WEAKENED. It used to allow no write anywhere; 5d allowed exactly one file
    and 5e allows exactly two, BY NAME. A blanket exemption ("the service may write") would be
    the weakening, and it is the easy edit when this goes red, which is why the list above is
    explicit and this docstring says so.

    RECURSIVE (rglob, not glob). The old version globbed the package's top level only, so a
    subpackage could have carried a write with nothing to say so.

    The check is crude on purpose: it does not parse SQL, it refuses the keywords outright, so a
    write cannot arrive disguised as a clever construction.
    """
    package = Path(reads_module.__file__).parent
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        if path.name in _WRITE_MODULES:
            continue
        code = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("#")
        )
        # Strip docstrings: several of them discuss writes in order to explain their absence.
        body = "".join(code.split('"""')[::2])
        for keyword in ("INSERT INTO", "UPDATE ", "DELETE FROM", "TRUNCATE", "ALTER TABLE"):
            if keyword in body.upper():
                offenders.append(f"{path.name} contains {keyword!r}")
    assert offenders == [], (
        "synapse-ui-server writes ONLY through "
        + ", ".join(f"{name} ({what})" for name, what in sorted(_WRITE_MODULES.items()))
        + f". Found writes elsewhere: {offenders}"
    )


def test_the_lifecycle_module_holds_exactly_one_sql_statement() -> None:
    """THE EXEMPTION IS BOUNDED, or it is not an exemption.

    ASSERTED ON THE STATEMENT OBJECTS, not on source text, and the first attempt is why: the
    text-stripping helper the sibling test uses removes triple-quoted blocks to drop docstrings,
    which also removed the SQL literal — so the check read an empty body and failed against
    correct code. Enumerating the module's TextClause constants asks the real question ("what
    SQL can this module execute") instead of a proxy for it.
    """
    import synapse_ui_server.lifecycle as lifecycle_module
    from sqlalchemy import TextClause

    statements = {
        name: str(value) for name, value in vars(lifecycle_module).items() if isinstance(value, TextClause)
    }
    assert len(statements) == 1, f"the write surface grew: {sorted(statements)}"
    (sql,) = statements.values()
    assert "INSERT INTO synapse.action_events" in sql
    for keyword in ("UPDATE ", "DELETE ", "TRUNCATE", "ALTER TABLE", "SELECT "):
        assert keyword not in sql.upper(), f"the lifecycle statement contains {keyword!r}"


def test_the_provision_module_holds_exactly_three_statements_and_writes_with_one() -> None:
    """THE SECOND EXEMPTION IS BOUNDED TOO, and its bound is three rather than one.

    WHY THREE AND NOT ONE. The two extra statements ARE the pre-flight, and the pre-flight is the
    point of the write: an unknown tenant UUID inserts fine, enumerates fine, and produces a
    healthy run with zero actions every day for ever with nothing going red. Both checks have to
    run in the SAME TRANSACTION as the insert or they are advice, which is why the credential
    holds two SELECTs at all.

    SO THIS ASSERTS THE SHAPE, NOT THE COUNT ALONE. Three statements, exactly one of which is a
    write, and the two reads are the two the grant permits and no others. A fourth statement, or
    a second write, or a read of a third table, fails here.
    """
    import synapse_ui_server.provision as provision_module
    from sqlalchemy import TextClause

    statements = {
        name: str(value) for name, value in vars(provision_module).items() if isinstance(value, TextClause)
    }
    assert len(statements) == 3, f"the provisioning surface changed size: {sorted(statements)}"

    writes = [sql for sql in statements.values() if "INSERT INTO" in sql.upper()]
    assert len(writes) == 1, "provision.py must contain exactly one write"
    (insert,) = writes
    assert "INSERT INTO synapse.provision" in insert
    # ON CONFLICT IS IN THIS LIST FOR THE SAME REASON RETURNING IS: both need SELECT on
    # synapse.provision, which this credential deliberately does not hold. The clause was here
    # once and every enable in production failed with `permission denied for table provision`
    # until 2026-08-10. A duplicate is reported from SQLSTATE 23505 instead.
    for keyword in ("UPDATE ", "DELETE ", "TRUNCATE", "ALTER TABLE", "RETURNING", "ON CONFLICT"):
        assert keyword not in insert.upper(), f"the provisioning statement contains {keyword!r}"

    # THE PRE-FLIGHT READS EXACTLY THE TWO TABLES THE GRANT COVERS. A read of anything else is
    # both a permission error at runtime and a widening of the credential in
    # 05_synapse_provisioner_grant.sql that nobody asked for.
    read_tables = {
        table
        for sql in statements.values()
        for table in re.findall(r"\bFROM\s+([a-z_]+\.[a-z_]+)", sql, re.I)
    }
    assert read_tables == {
        "identity_mirror.tenants",
        "canonical.store_sku_current_position",
    }, f"the provisioning pre-flight reads something the grant does not cover: {sorted(read_tables)}"


def test_cadence_and_rung_are_constants_not_parameters() -> None:
    """THE FLEET-BREAKING ONE. A wrong rung does not break the tenant it was set on.

    check_envelope runs when the ORCHESTRATOR LOADS synapse.provision and raises for the WHOLE
    list, so one provision naming a rung above its analysis's declared max_rung stops the 04:00
    sweep for EVERY tenant. The DDL's ck_provision_rung permits 'suggest' because Rung declares
    it, and NOTHING IMPLEMENTS 'suggest', so a dropdown built by reading the CHECK constraint
    would offer a one-click fleet outage that passes every database constraint.

    ASSERTED ON THE SIGNATURE, because that is the thing that would change. A value that cannot
    be passed cannot be mistyped, and this fails the moment either becomes reachable from a
    caller.
    """
    import inspect

    from synapse_ui_server.main import EnableBody
    from synapse_ui_server.provision import CADENCE, RUNG, enable_analysis

    assert CADENCE == "daily"
    assert RUNG == "shadow"

    parameters = set(inspect.signature(enable_analysis).parameters)
    for forbidden in ("cadence", "rung"):
        assert forbidden not in parameters, (
            f"{forbidden} became a parameter of enable_analysis. It is hardcoded because the "
            "envelope check refuses the whole enumeration rather than one row"
        )

    # AND NOT REACHABLE FROM THE WIRE EITHER. A field here would be settable by anything that can
    # post to the endpoint, whatever the function signature says.
    assert set(EnableBody.model_fields) == {"timezone"}, (
        "the enable request body grew a field. cadence, rung, tenant and analysis are all "
        "deliberately not settable; see EnableBody"
    )


def test_the_writes_are_tenant_scoped_not_platform() -> None:
    """FORCED BY THE POLICY, not chosen, and true of BOTH write modules.

    action_events and provision both carry WITH CHECK (tenant_id = app.tenant_id), and
    rls_platform_session sets that GUC to '' — so a PLATFORM session matches no row and the
    insert is refused. These are the only two places in the service where the tenant-scoped
    helper is correct, and reads.py must never acquire it.
    """
    import synapse_ui_server.lifecycle as lifecycle_module
    import synapse_ui_server.provision as provision_module

    for module in (lifecycle_module, provision_module):
        # __file__ is Optional on ModuleType. A None here would mean a namespace package,
        # which these are not, and asserting says so rather than silencing the checker.
        assert module.__file__ is not None
        source = Path(module.__file__).read_text(encoding="utf-8")
        body = "".join(source.split('"""')[::2])
        assert "rls_session(" in body, f"{module.__name__} does not open a tenant-scoped session"
        assert "rls_platform_session(" not in body, (
            f"{module.__name__} opened a PLATFORM session; its WITH CHECK would refuse the write"
        )


def test_the_only_session_helper_used_is_the_platform_one() -> None:
    """``rls_platform_session(engine, None)`` sets the tenant GUC to '' , so every policy's
    WITH CHECK matches no row — the session is physically incapable of writing. A plain
    ``rls_session`` here would be tenant-scoped AND write-capable."""
    source = Path(reads_module.__file__).read_text(encoding="utf-8")
    assert "rls_platform_session" in source
    body = "".join(source.split('"""')[::2])
    assert "rls_session(" not in body, (
        "reads.py opened a tenant-scoped session; that one can write, and this service must not"
    )


def test_the_service_exposes_no_schema_endpoints() -> None:
    """/docs, /redoc and /openapi.json are the only routes FastAPI mounts WITHOUT a
    dependency, so any caller able to invoke could enumerate the API without being PLATFORM.

    Asserted rather than merely configured, because the reason for removing them is that this
    service is the precedent for fixing the other four — and a precedent that can be undone by
    a default in a later FastAPI version is not one. Today's risk is low; the point is that
    "safe behind two layers" is how a public schema happens when one layer changes.
    """
    from synapse_ui_server.config import Config
    from synapse_ui_server.main import create_app

    app = create_app(
        Config(
            reader_url="postgresql+psycopg://u@h/d",
            lifecycle_url="postgresql+psycopg://l@h/d",
            provision_url="postgresql+psycopg://p@h/d",
            cm_api_base_url="https://cm.example",
            jwt_issuer="https://x/",
            jwt_audience="a",
            expected_database="thalamus",
            axon_sender_url="postgresql+psycopg://a@h/d",
            axon_sendgrid_api_key="test-key",
            axon_sendgrid_from_email="noreply@test.invalid",
            axon_platform_oncall_email="oncall@test.invalid",
        )
    )
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert not paths & {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}, (
        f"a schema endpoint is mounted: {sorted(paths & {'/docs', '/redoc', '/openapi.json'})}"
    )
    # The baseline: the real routes are still there, so this cannot pass against an app that
    # failed to build at all.
    assert {"/healthz", "/fleet", "/analyses"} <= paths
