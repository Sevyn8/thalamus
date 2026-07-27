"""Vault logic against an in-memory backend, plus the Google adapter against a fake client.

No network. The meat (naming + payload + read/write + the D5 prune policy) is tested through
the SecretBackend Protocol; the GCP adapter is tested through a fake SecretManager client.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

import pytest
from google.api_core.exceptions import NotFound, PermissionDenied

from thalamus_clover_oauth.payload import CloverTokenSet
from thalamus_clover_oauth.vault import CloverTokenVault, GoogleSecretBackend

# The google-api-core exception constructors are untyped; call them through an Any alias so
# mypy --strict does not flag a no-untyped-call in tests (the square-oauth tests do the same).
_NotFound: Any = NotFound
_PermissionDenied: Any = PermissionDenied

_TENANT = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")
_SOURCE = "clover_pos_v1"
_PROJECT = "sevyn8-thalamus-staging"


def _record(access: str = "atok", previous: str | None = None) -> CloverTokenSet:
    return CloverTokenSet(
        access_token=access,
        access_token_expiration=1_785_000_000,
        refresh_token="clvroar-current",
        refresh_token_expiration=1_816_000_000,
        previous_refresh_token=previous,
        previous_rotated_at=None if previous is None else 1_780_000_000,
        merchant_id="0RKKDBMKPAH71",
        employee_id="EMP1",
        obtained_at=1_784_000_000,
        environment="sandbox",
    )


class _FakeBackend:
    """In-memory SecretBackend that models VERSIONS, not just a latest value."""

    def __init__(self) -> None:
        self.versions: dict[str, list[str]] = {}  # secret_id -> version names, oldest first
        self.data: dict[str, bytes] = {}  # version name -> bytes
        self.destroyed: list[str] = []
        self.list_error: Exception | None = None
        self.destroy_error: Exception | None = None

    def _name(self, secret_id: str, number: int) -> str:
        return f"projects/{_PROJECT}/secrets/{secret_id}/versions/{number}"

    def access_latest(self, secret_id: str) -> bytes | None:
        names = self.versions.get(secret_id)
        if not names:
            return None
        return self.data[names[-1]]

    def add_version(self, secret_id: str, data: bytes) -> None:
        names = self.versions.setdefault(secret_id, [])
        name = self._name(secret_id, len(names) + 1)
        names.append(name)
        self.data[name] = data

    def list_enabled_versions(self, secret_id: str) -> list[str]:
        if self.list_error is not None:
            raise self.list_error
        live = [n for n in self.versions.get(secret_id, []) if n not in self.destroyed]
        return list(reversed(live))  # newest first

    def destroy_version(self, version_name: str) -> None:
        if self.destroy_error is not None:
            raise self.destroy_error
        self.destroyed.append(version_name)


# -- read / write round trip ---------------------------------------------------------


def test_read_missing_returns_none() -> None:
    assert CloverTokenVault(_FakeBackend()).read(_TENANT, _SOURCE) is None


def test_write_then_read_round_trips() -> None:
    vault = CloverTokenVault(_FakeBackend())
    record = _record(previous="clvroar-prev")
    vault.write(_TENANT, _SOURCE, record)
    assert vault.read(_TENANT, _SOURCE) == record


def test_write_twice_latest_wins() -> None:
    vault = CloverTokenVault(_FakeBackend())
    vault.write(_TENANT, _SOURCE, _record("first"))
    vault.write(_TENANT, _SOURCE, _record("second"))
    read = vault.read(_TENANT, _SOURCE)
    assert read is not None
    assert read.access_token == "second"


# -- D5: version lifecycle -----------------------------------------------------------


def test_prune_is_a_no_op_until_there_are_more_than_keep_versions() -> None:
    backend = _FakeBackend()
    vault = CloverTokenVault(backend)
    vault.write(_TENANT, _SOURCE, _record("v1"))
    vault.write(_TENANT, _SOURCE, _record("v2"))
    assert backend.destroyed == []


def test_prune_destroys_the_oldest_and_keeps_current_plus_previous() -> None:
    backend = _FakeBackend()
    vault = CloverTokenVault(backend)
    for n in range(1, 6):  # five rotations
        vault.write(_TENANT, _SOURCE, _record(f"v{n}"))

    secret_id = next(iter(backend.versions))
    all_names = backend.versions[secret_id]
    # Versions 1..3 destroyed; 4 (previous) and 5 (current) kept.
    assert backend.destroyed == all_names[:3]
    assert all_names[3] not in backend.destroyed
    assert all_names[4] not in backend.destroyed
    # And the surviving latest still reads back.
    read = vault.read(_TENANT, _SOURCE)
    assert read is not None
    assert read.access_token == "v5"


def test_prune_keep_count_is_configurable() -> None:
    backend = _FakeBackend()
    vault = CloverTokenVault(backend, keep_versions=1)
    for n in range(1, 4):
        vault.write(_TENANT, _SOURCE, _record(f"v{n}"))
    assert len(backend.destroyed) == 2


def test_the_recovery_credential_survives_pruning() -> None:
    # THE reason keeping only two versions is safe: previous_refresh_token lives INSIDE the
    # current version's payload, not in a superseded version, so the prune cannot destroy it.
    backend = _FakeBackend()
    vault = CloverTokenVault(backend)
    for n in range(1, 6):
        vault.write(_TENANT, _SOURCE, _record(f"v{n}", previous=f"clvroar-spent-{n}"))
    read = vault.read(_TENANT, _SOURCE)
    assert read is not None
    assert read.previous_refresh_token == "clvroar-spent-5"


# -- D5: the prune must never lose the write -----------------------------------------


def test_a_destroy_failure_does_not_lose_the_token() -> None:
    # The token is already durable by the time the prune runs. Raising here would report a
    # persistence failure that did not happen — and on Clover that misreport IS the
    # lost-write scenario it would be claiming.
    backend = _FakeBackend()
    backend.destroy_error = _PermissionDenied("missing secretmanager.versions.destroy")
    vault = CloverTokenVault(backend)
    for n in range(1, 4):
        vault.write(_TENANT, _SOURCE, _record(f"v{n}"))  # must not raise
    read = vault.read(_TENANT, _SOURCE)
    assert read is not None
    assert read.access_token == "v3"
    assert backend.destroyed == []  # nothing pruned, but nothing lost either


def test_a_list_failure_does_not_lose_the_token() -> None:
    backend = _FakeBackend()
    backend.list_error = _PermissionDenied("missing secretmanager.versions.list")
    vault = CloverTokenVault(backend)
    vault.write(_TENANT, _SOURCE, _record("v1"))  # must not raise
    assert vault.read(_TENANT, _SOURCE) is not None


def test_an_add_failure_does_raise() -> None:
    # The asymmetry that matters: a failed ADD must surface. A swallowed write means the
    # rotation is lost and the merchant is one step from re-consent.
    class _AddFails(_FakeBackend):
        def add_version(self, secret_id: str, data: bytes) -> None:
            raise _PermissionDenied("no write access")

    with pytest.raises(PermissionDenied):
        CloverTokenVault(_AddFails()).write(_TENANT, _SOURCE, _record())


def test_a_programming_error_in_the_prune_is_not_swallowed() -> None:
    # The swallow is narrow on purpose. A blanket `except Exception` here would absorb a
    # TypeError from a drifted signature and the prune would silently stop working — the
    # exact failure mode that hid a health-emit bug elsewhere in this repo for weeks.
    backend = _FakeBackend()
    backend.destroy_error = TypeError("destroy_version() got an unexpected keyword argument")
    vault = CloverTokenVault(backend)
    with pytest.raises(TypeError):
        for n in range(1, 4):
            vault.write(_TENANT, _SOURCE, _record(f"v{n}"))


# -- the Google adapter --------------------------------------------------------------


class _FakeVersion:
    def __init__(self, name: str, state: str) -> None:
        self.name = name
        self.state = state


class _FakeSecretApi:
    """A stand-in for SecretManagerServiceClient covering exactly the five calls made."""

    def __init__(self, *, existing: dict[str, bytes] | None = None) -> None:
        self.store: dict[str, bytes] = existing or {}
        self.created: list[str] = []
        self.added: list[tuple[str, bytes]] = []
        self.destroyed: list[str] = []
        self.versions: list[_FakeVersion] = []

    def access_secret_version(self, *, name: str) -> Any:
        secret = name.rsplit("/versions/", 1)[0]
        if secret not in self.store:
            raise _NotFound("no such secret")

        class _R:
            payload = type("_P", (), {"data": self.store[secret]})()

        return _R()

    def add_secret_version(self, *, parent: str, payload: dict[str, bytes]) -> object:
        if parent not in self.store and parent not in self.created:
            raise _NotFound("no such secret")
        self.store[parent] = payload["data"]
        self.added.append((parent, payload["data"]))
        return object()

    def create_secret(self, *, parent: str, secret_id: str, secret: dict[str, Any]) -> object:
        self.created.append(f"{parent}/secrets/{secret_id}")
        return object()

    def list_secret_versions(self, *, parent: str) -> Any:
        return self.versions

    def destroy_secret_version(self, *, name: str) -> object:
        self.destroyed.append(name)
        return object()


def _backend(api: _FakeSecretApi) -> GoogleSecretBackend:
    return GoogleSecretBackend(project_id=_PROJECT, api=api)


def test_adapter_read_missing_maps_notfound_to_none() -> None:
    assert _backend(_FakeSecretApi()).access_latest("clover-oauth-x") is None


def test_adapter_first_write_creates_then_adds() -> None:
    api = _FakeSecretApi()
    _backend(api).add_version("clover-oauth-x", b"payload")
    assert api.created == [f"projects/{_PROJECT}/secrets/clover-oauth-x"]
    assert api.added[-1][1] == b"payload"


def test_adapter_lists_only_enabled_versions_newest_first() -> None:
    api = _FakeSecretApi()
    api.versions = [
        _FakeVersion(f"projects/{_PROJECT}/secrets/s/versions/1", "DESTROYED"),
        _FakeVersion(f"projects/{_PROJECT}/secrets/s/versions/2", "ENABLED"),
        _FakeVersion(f"projects/{_PROJECT}/secrets/s/versions/10", "ENABLED"),
        _FakeVersion(f"projects/{_PROJECT}/secrets/s/versions/3", "DISABLED"),
    ]
    names = _backend(api).list_enabled_versions("s")
    # 10 before 2: sorted by version NUMBER, not lexically and not by API order.
    assert names == [
        f"projects/{_PROJECT}/secrets/s/versions/10",
        f"projects/{_PROJECT}/secrets/s/versions/2",
    ]


def test_adapter_destroy_passes_the_version_name_through() -> None:
    api = _FakeSecretApi()
    name = f"projects/{_PROJECT}/secrets/s/versions/1"
    _backend(api).destroy_version(name)
    assert api.destroyed == [name]
