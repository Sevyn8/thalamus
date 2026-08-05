"""This service cannot write. Not "does not" — cannot, and these are what make that a property.

THE ARGUMENT, one layer up from slice 5. ``synapse_writer`` holds INSERT and no SELECT, so
"resolvers never write" is a runtime fact rather than a grep. The same reasoning applies to a
read-only service: one that merely CHOOSES not to write is equivalent in behaviour and not in
property. A service with no writer credential cannot be made to write by a bug, a merge, or a
contributor in a hurry.

Slice 8b needs a writer for provisioning. It must add one DELIBERATELY — which is what these
tests turn into a visible act rather than a discovery that it was already wired.
"""

from __future__ import annotations

from dataclasses import fields
from pathlib import Path

import pytest
import synapse_ui_server.reads as reads_module
from synapse_ui_server.config import Config, load_config


def test_the_config_has_no_writer_field() -> None:
    """A field that does not exist cannot be populated by a stray environment variable."""
    assert "writer_url" not in {field.name for field in fields(Config)}


def test_a_writer_dsn_in_the_environment_is_a_startup_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NOT A WARNING. A writer DSN present here means somebody wired one expecting it to be
    used, and nothing in this service can. Failing beats a live credential sitting unused in a
    revision's environment, reachable by anything that can read the config."""
    monkeypatch.setenv("SYNAPSE_READER_URL", "postgresql+psycopg://r@localhost/db")
    monkeypatch.setenv("SYNAPSE_JWT_ISSUER", "https://example.auth0.com/")
    monkeypatch.setenv("SYNAPSE_JWT_AUDIENCE", "https://api.example")
    monkeypatch.setenv("SYNAPSE_WRITER_URL", "postgresql+psycopg://w@localhost/db")

    with pytest.raises(RuntimeError, match="holds no write path"):
        load_config()


def test_the_config_loads_without_a_writer(monkeypatch: pytest.MonkeyPatch) -> None:
    """The baseline. Without it the test above would pass against a loader that always raised."""
    monkeypatch.delenv("SYNAPSE_WRITER_URL", raising=False)
    monkeypatch.setenv("SYNAPSE_READER_URL", "postgresql+psycopg://r@localhost/db")
    monkeypatch.setenv("SYNAPSE_JWT_ISSUER", "https://example.auth0.com/")
    monkeypatch.setenv("SYNAPSE_JWT_AUDIENCE", "https://api.example")
    assert load_config().reader_url.endswith("/db")


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


def test_no_module_in_this_service_issues_a_write() -> None:
    """GREPPED, because a read-only service is a claim about every statement it can execute.

    Bounded to this package's own source. The check is crude on purpose: it does not attempt to
    parse SQL, it refuses the keywords outright, so a write cannot arrive disguised as a clever
    construction either.
    """
    package = Path(reads_module.__file__).parent
    offenders: list[str] = []
    for path in sorted(package.glob("*.py")):
        code = "\n".join(
            line for line in path.read_text(encoding="utf-8").splitlines() if not line.strip().startswith("#")
        )
        # Strip docstrings: several of them discuss writes in order to explain their absence.
        body = "".join(code.split('"""')[::2])
        for keyword in ("INSERT INTO", "UPDATE ", "DELETE FROM", "TRUNCATE", "ALTER TABLE"):
            if keyword in body.upper():
                offenders.append(f"{path.name} contains {keyword!r}")
    assert offenders == [], f"synapse-ui-server is read-only in slice 8a: {offenders}"


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
