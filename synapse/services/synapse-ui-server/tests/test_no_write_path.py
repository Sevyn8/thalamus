"""This service writes ONE table through ONE credential, and these are what keep it there.

IT WAS READ-ONLY UNTIL SLICE 5d, and the change was the deliberate act this file demanded. The
old header said "Slice 8b needs a writer for provisioning. It must add one DELIBERATELY — which
is what these tests turn into a visible act rather than a discovery that it was already wired."
The write that arrived was the alert lifecycle instead, and the mechanism worked as designed:
adding it meant editing this file, in the open, with the reasoning attached.

WHAT THE CONTRACT IS NOW. Not "cannot write" — "cannot write anything except an append to
synapse.action_events, as a role that can do nothing else". The distinction is still a property
rather than an intention, and the property is enforced in three places, only one of which is
Python:

  - THE GRANT. synapse_lifecycle holds INSERT on synapse.action_events. No SELECT, no UPDATE,
    no DELETE, no other table (migration 0006). Postgres refuses everything else whatever this
    code says.
  - THE TRIGGER. That table is append-only and binds the owner too.
  - THE MODULE BOUNDARY. lifecycle.py is the only file here allowed to contain a write, which
    is what test_no_module_outside_lifecycle_issues_a_write asserts.

SYNAPSE_WRITER_URL IS STILL REFUSED. That is the ORCHESTRATOR's credential and it can append to
the action log itself; a console holding it would make every row ambiguous about whether a human
or the 04:00 sweep produced it.

THE ARGUMENT, one layer up from slice 5. ``synapse_writer`` holds INSERT and no SELECT, so
"resolvers never write" is a runtime fact rather than a grep. The same reasoning applies to a
read-only service: one that merely CHOOSES not to write is equivalent in behaviour and not in
property. A service with no writer credential cannot be made to write by a bug, a merge, or a
contributor in a hurry.

"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest
import synapse_ui_server.reads as reads_module
from synapse_ui_server.config import Config, load_config


def test_the_config_has_no_orchestrator_writer_field() -> None:
    """A field that does not exist cannot be populated by a stray environment variable.

    ``lifecycle_url`` exists now; ``writer_url`` still must not. The two are different
    credentials with different blast radii, and the console is only entitled to the smaller.
    """
    names = {field.name for field in fields(Config)}
    assert "writer_url" not in names
    assert "lifecycle_url" in names, "the lifecycle DSN is required; slice 5d writes with it"


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


def test_the_config_loads_with_the_lifecycle_dsn_and_no_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline. Without it the test above would pass against a loader that always raised."""
    _base_env(monkeypatch)
    config = load_config()
    assert config.reader_url.endswith("/db")
    assert config.lifecycle_url.endswith("/db")


def test_the_lifecycle_dsn_is_required(monkeypatch: pytest.MonkeyPatch) -> None:
    """A service that cannot write is not the goal any more — a service that SILENTLY cannot
    write is worse than one that refuses to start. Every lifecycle POST would 500 at runtime."""
    _base_env(monkeypatch)
    monkeypatch.delenv("SYNAPSE_LIFECYCLE_URL", raising=False)
    with pytest.raises(RuntimeError, match="SYNAPSE_LIFECYCLE_URL"):
        load_config()


def _base_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SYNAPSE_WRITER_URL", raising=False)
    monkeypatch.setenv("SYNAPSE_READER_URL", "postgresql+psycopg://r@localhost/db")
    monkeypatch.setenv("SYNAPSE_LIFECYCLE_URL", "postgresql+psycopg://l@localhost/db")
    monkeypatch.setenv("SYNAPSE_JWT_ISSUER", "https://example.auth0.com/")
    monkeypatch.setenv("SYNAPSE_JWT_AUDIENCE", "https://api.example")


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


def test_no_module_outside_lifecycle_issues_a_write() -> None:
    """GREPPED, because the claim is about every statement this service can execute.

    RESHAPED IN 5d, NOT WEAKENED. It used to allow no write anywhere; it now allows exactly one
    file. A blanket exemption ("the service may write") would have been the weakening — this
    names the single module, so a second write surface fails here and has to be argued for.

    RECURSIVE NOW (rglob, not glob). The old version globbed the package's top level only, so a
    subpackage could have carried a write with nothing to say so. Nothing exploited that; it was
    a hole in the guard rather than in the service, and it is closed here because this is the
    slice that made writes possible at all.

    The check is crude on purpose: it does not parse SQL, it refuses the keywords outright, so a
    write cannot arrive disguised as a clever construction.
    """
    package = Path(reads_module.__file__).parent
    offenders: list[str] = []
    for path in sorted(package.rglob("*.py")):
        if path.name == "lifecycle.py":
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
        "synapse-ui-server writes ONLY through lifecycle.py, which is the single INSERT the "
        f"synapse_lifecycle grant permits. Found writes elsewhere: {offenders}"
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


def test_the_lifecycle_write_is_tenant_scoped_not_platform() -> None:
    """FORCED BY THE POLICY, not chosen. action_events' WITH CHECK compares app.tenant_id, and
    rls_platform_session sets that GUC to '' — so a PLATFORM session matches no row and the
    insert is refused. This is the one place in the service where the tenant-scoped helper is
    correct, and reads.py must never acquire it."""
    import synapse_ui_server.lifecycle as lifecycle_module

    source = Path(lifecycle_module.__file__).read_text(encoding="utf-8")
    body = "".join(source.split('"""')[::2])
    assert "rls_session(" in body
    assert "rls_platform_session(" not in body


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
            jwt_issuer="https://x/",
            jwt_audience="a",
            expected_database="thalamus",
        )
    )
    paths = {route.path for route in app.routes if hasattr(route, "path")}
    assert not paths & {"/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"}, (
        f"a schema endpoint is mounted: {sorted(paths & {'/docs', '/redoc', '/openapi.json'})}"
    )
    # The baseline: the real routes are still there, so this cannot pass against an app that
    # failed to build at all.
    assert {"/healthz", "/fleet", "/analyses"} <= paths
