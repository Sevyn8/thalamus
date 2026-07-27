"""CloverTokenStore: the D2 read-rotate-PERSIST-return ordering, D3 caching, D4 recovery.

Offline: an in-memory vault backend and a recording fake client. Nothing here touches the
network or GCP.

The ordering assertions are the point of the slice. Clover refresh tokens are single-use, so
the instant the vendor answers a refresh, the token we sent is dead and the replacement
exists only in process memory. Every test below that mentions "order" is guarding the window
in which a crash costs a merchant.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from thalamus_clover_oauth.errors import (
    CloverOAuthNotConnectedError,
    CloverOAuthRecoveryExhaustedError,
    CloverOAuthRefreshRejectedError,
    CloverOAuthTransientError,
)
from thalamus_clover_oauth.payload import ACCESS_TOKEN_LIFETIME_SECONDS, CloverTokenSet
from thalamus_clover_oauth.token_store import DEFAULT_REFRESH_SKEW, CloverTokenStore
from thalamus_clover_oauth.vault import CloverTokenVault

_TENANT = UUID("019f9d6d-c032-7e03-a232-ee77299f9b5d")
_SOURCE = "clover_pos_v1"
_MERCHANT = "0RKKDBMKPAH71"

_NOW = datetime(2026, 8, 1, 12, 0, 0, tzinfo=UTC)
_NOW_TS = int(_NOW.timestamp())
_SKEW = timedelta(minutes=5)


def _record(
    *,
    access: str = "access-1",
    refresh: str = "clvroar-1",
    previous: str | None = None,
    access_exp_offset: int = 30 * 60,
    refresh_exp_offset: int = 365 * 24 * 60 * 60,
) -> CloverTokenSet:
    return CloverTokenSet(
        access_token=access,
        access_token_expiration=_NOW_TS + access_exp_offset,
        refresh_token=refresh,
        refresh_token_expiration=_NOW_TS + refresh_exp_offset,
        previous_refresh_token=previous,
        previous_rotated_at=None if previous is None else _NOW_TS - 3600,
        merchant_id=_MERCHANT,
        employee_id="EMP1",
        obtained_at=_NOW_TS - 60,
        environment="sandbox",
    )


class _Backend:
    """In-memory SecretBackend, recording every effect in ORDER."""

    def __init__(self, log: list[str]) -> None:
        self.blob: bytes | None = None
        self.log = log
        self.writes = 0

    def access_latest(self, secret_id: str) -> bytes | None:
        self.log.append("read")
        return self.blob

    def add_version(self, secret_id: str, data: bytes) -> None:
        self.log.append("persist")
        self.writes += 1
        self.blob = data

    def list_enabled_versions(self, secret_id: str) -> list[str]:
        return []

    def destroy_version(self, version_name: str) -> None:  # pragma: no cover - never reached
        raise AssertionError("no versions to prune in these tests")


class _Client:
    """A recording CloverOAuthClient stand-in."""

    def __init__(
        self,
        log: list[str],
        *,
        refresh_error: Exception | None = None,
        recover_error: Exception | None = None,
        recover_rejects: set[str] | None = None,
    ) -> None:
        self.log = log
        self.refresh_error = refresh_error
        self.recover_error = recover_error
        # Tokens the recovery leg rejects; anything else is accepted. Lets a test model
        # Clover's real behaviour, where exactly ONE generation is recovery-eligible.
        self.recover_rejects = recover_rejects or set()
        self.refreshed_with: list[str] = []
        self.recovered_with: list[str] = []

    def refresh(self, refresh_token: str, *, merchant_id: str, employee_id: str | None) -> CloverTokenSet:
        self.log.append("refresh")
        self.refreshed_with.append(refresh_token)
        if self.refresh_error is not None:
            raise self.refresh_error
        return _record(access="access-2", refresh="clvroar-2")

    def recover(self, recovery_token: str, *, merchant_id: str, employee_id: str | None) -> CloverTokenSet:
        self.log.append("recover")
        self.recovered_with.append(recovery_token)
        if self.recover_error is not None:
            raise self.recover_error
        if recovery_token in self.recover_rejects:
            raise CloverOAuthRecoveryExhaustedError(f"401 for {recovery_token}")
        return _record(access="access-3", refresh="clvroar-3")


def _store(
    log: list[str],
    *,
    stored: CloverTokenSet | None,
    refresh_error: Exception | None = None,
    recover_error: Exception | None = None,
    recover_rejects: set[str] | None = None,
    backend: _Backend | None = None,
) -> tuple[CloverTokenStore, _Backend, _Client]:
    backend = backend or _Backend(log)
    if stored is not None:
        backend.blob = stored.to_json().encode()
    vault = CloverTokenVault(backend)
    client = _Client(
        log,
        refresh_error=refresh_error,
        recover_error=recover_error,
        recover_rejects=recover_rejects,
    )
    store = CloverTokenStore(
        vault=vault,
        client=client,  # type: ignore[arg-type]
        refresh_skew=_SKEW,
        clock=lambda: _NOW,
    )
    return store, backend, client


# -- D3: the skew-valid path writes NOTHING ------------------------------------------


def test_a_token_valid_within_skew_is_used_and_nothing_is_written() -> None:
    log: list[str] = []
    store, backend, client = _store(log, stored=_record())
    assert store.get_token(_TENANT, _SOURCE) == "access-1"
    assert log == ["read"]  # no refresh, no persist
    assert backend.writes == 0
    assert client.refreshed_with == []


def test_repeated_reads_inside_the_window_collapse_to_zero_rotations() -> None:
    # D3's real payoff: a burst (retries, a multi-domain trigger, an operator poking the
    # CLI) must not burn several of Clover's capped live refresh tokens.
    log: list[str] = []
    store, backend, client = _store(log, stored=_record())
    for _ in range(5):
        store.get_token(_TENANT, _SOURCE)
    assert backend.writes == 0
    assert client.refreshed_with == []


# -- D2: rotate, PERSIST, then return -------------------------------------------------


def test_a_stale_token_rotates_and_persists_before_returning() -> None:
    log: list[str] = []
    store, backend, _ = _store(log, stored=_record(access_exp_offset=60))  # inside skew
    token = store.get_token(_TENANT, _SOURCE)
    assert token == "access-2"
    # THE ordering assertion: persist strictly precedes the return.
    assert log == ["read", "refresh", "persist"]
    assert backend.writes == 1


def test_the_persisted_record_names_the_token_it_just_spent() -> None:
    # Without this stamp the new record has no recovery credential, and the next lost write
    # is unrecoverable.
    log: list[str] = []
    store, backend, _ = _store(log, stored=_record(refresh="clvroar-1", access_exp_offset=60))
    store.get_token(_TENANT, _SOURCE)
    assert backend.blob is not None
    persisted = CloverTokenSet.from_json(backend.blob.decode())
    assert persisted.refresh_token == "clvroar-2"  # the new one
    assert persisted.previous_refresh_token == "clvroar-1"  # the one just spent
    assert persisted.previous_rotated_at == _NOW_TS


def test_a_crash_between_persist_and_return_does_not_lose_the_chain() -> None:
    # Simulate the process dying immediately after the vault write by reading the vault
    # back with a FRESH store, as the next run would. The rotation must already be durable
    # and the chain intact — this is precisely what use-then-persist would lose.
    log: list[str] = []
    store, backend, _ = _store(log, stored=_record(refresh="clvroar-1", access_exp_offset=60))
    store.get_token(_TENANT, _SOURCE)

    survivor = CloverTokenVault(backend).read(_TENANT, _SOURCE)
    assert survivor is not None
    assert survivor.access_token == "access-2"
    assert survivor.refresh_token == "clvroar-2"
    assert survivor.previous_refresh_token == "clvroar-1"


def test_a_persist_failure_propagates_and_returns_no_token() -> None:
    # Better a failed run than a used-but-unpersisted rotation: the caller must never hold
    # a token whose refresh chain is not durable.
    log: list[str] = []

    class _WriteFails(_Backend):
        def add_version(self, secret_id: str, data: bytes) -> None:
            self.log.append("persist-failed")
            raise RuntimeError("secret manager unavailable")

    store, _, _ = _store(log, stored=_record(access_exp_offset=60), backend=_WriteFails(log))
    with pytest.raises(RuntimeError):
        store.get_token(_TENANT, _SOURCE)
    assert log == ["read", "refresh", "persist-failed"]


# -- D4: recovery on a rejected refresh ------------------------------------------------


def test_recovery_tries_the_just_rejected_token_first() -> None:
    # A spent refresh token is invalid as a REFRESH token but valid as a RECOVERY token for
    # ~2 weeks: same string, two roles. When our persist was the thing that failed, the
    # recovery-eligible generation is the one we just presented — NOT previous, which is two
    # generations back.
    log: list[str] = []
    store, _, client = _store(
        log,
        stored=_record(refresh="clvroar-N", previous="clvroar-N-1", access_exp_offset=60),
        refresh_error=CloverOAuthRefreshRejectedError("401", detail="spent"),
    )
    assert store.get_token(_TENANT, _SOURCE) == "access-3"
    assert client.recovered_with == ["clvroar-N"]  # current first, previous never reached
    assert log == ["read", "refresh", "recover", "persist"]


def test_recovery_falls_back_to_previous_when_the_current_is_rejected() -> None:
    # The other shape: the rotation itself never took effect, so the stored current was
    # never spent and is not recovery-eligible; the preceding generation is.
    log: list[str] = []
    store, _, client = _store(
        log,
        stored=_record(refresh="clvroar-N", previous="clvroar-N-1", access_exp_offset=60),
        refresh_error=CloverOAuthRefreshRejectedError("401"),
        recover_rejects={"clvroar-N"},
    )
    assert store.get_token(_TENANT, _SOURCE) == "access-3"
    assert client.recovered_with == ["clvroar-N", "clvroar-N-1"]  # in order


def test_the_winning_candidate_becomes_the_new_recovery_credential() -> None:
    log: list[str] = []
    store, backend, _ = _store(
        log,
        stored=_record(refresh="clvroar-N", previous="clvroar-N-1", access_exp_offset=60),
        refresh_error=CloverOAuthRefreshRejectedError("401"),
        recover_rejects={"clvroar-N"},
    )
    store.get_token(_TENANT, _SOURCE)
    assert backend.blob is not None
    persisted = CloverTokenSet.from_json(backend.blob.decode())
    # previous is what we PRESENTED to /recovery, not what happened to be stored before.
    assert persisted.previous_refresh_token == "clvroar-N-1"
    assert persisted.refresh_token == "clvroar-3"


def test_recovery_also_persists_before_returning() -> None:
    log: list[str] = []
    store, backend, _ = _store(
        log,
        stored=_record(refresh="clvroar-N", previous="clvroar-N-1", access_exp_offset=60),
        refresh_error=CloverOAuthRefreshRejectedError("401"),
    )
    store.get_token(_TENANT, _SOURCE)
    assert log[-1] == "persist"
    assert backend.blob is not None
    persisted = CloverTokenSet.from_json(backend.blob.decode())
    assert persisted.refresh_token == "clvroar-3"
    assert persisted.previous_refresh_token == "clvroar-N"


def test_recovery_is_attempted_even_without_a_recovery_available_hint() -> None:
    # Advisory only, never a gate: skipping a valid recovery costs the merchant, while a
    # needless attempt costs one HTTP call.
    log: list[str] = []
    store, _, client = _store(
        log,
        stored=_record(refresh="clvroar-N", previous="clvroar-N-1", access_exp_offset=60),
        refresh_error=CloverOAuthRefreshRejectedError("401", detail=None),
    )
    store.get_token(_TENANT, _SOURCE)
    assert client.recovered_with == ["clvroar-N"]


def test_no_previous_token_still_attempts_the_current_one() -> None:
    # A record with no previous is NOT a dead end: the lost-persist case is recoverable
    # from the current token alone, and that is the FIRST rotation's failure mode.
    log: list[str] = []
    store, _, client = _store(
        log,
        stored=_record(refresh="clvroar-N", previous=None, access_exp_offset=60),
        refresh_error=CloverOAuthRefreshRejectedError("401", detail="spent"),
    )
    assert store.get_token(_TENANT, _SOURCE) == "access-3"
    assert client.recovered_with == ["clvroar-N"]


def test_every_candidate_rejected_is_terminal_and_names_them() -> None:
    log: list[str] = []
    store, _, client = _store(
        log,
        stored=_record(refresh="clvroar-N", previous="clvroar-N-1", access_exp_offset=60),
        refresh_error=CloverOAuthRefreshRejectedError("401"),
        recover_rejects={"clvroar-N", "clvroar-N-1"},
    )
    with pytest.raises(CloverOAuthRecoveryExhaustedError) as exc:
        store.get_token(_TENANT, _SOURCE)
    assert client.recovered_with == ["clvroar-N", "clvroar-N-1"]
    assert "current, previous" in str(exc.value)


def test_a_failed_recovery_is_terminal_and_carries_the_diagnostic() -> None:
    log: list[str] = []
    store, _, _ = _store(
        log,
        stored=_record(previous="clvroar-0", access_exp_offset=60),
        refresh_error=CloverOAuthRefreshRejectedError("401", detail="X-Clover-Recovery-Available=false"),
        recover_error=CloverOAuthRecoveryExhaustedError("401", detail="outside the window"),
    )
    with pytest.raises(CloverOAuthRecoveryExhaustedError) as exc:
        store.get_token(_TENANT, _SOURCE)
    assert "outside the window" in (exc.value.detail or "")


def test_a_failed_recovery_falls_back_to_the_refresh_diagnostic() -> None:
    # When the recovery response carries no detail, the refresh 401's header hint is the
    # thing that explains the loss months later; it must not be dropped.
    log: list[str] = []
    store, _, _ = _store(
        log,
        stored=_record(previous="clvroar-0", access_exp_offset=60),
        refresh_error=CloverOAuthRefreshRejectedError("401", detail="X-Clover-Recovery-Available=true"),
        recover_error=CloverOAuthRecoveryExhaustedError("401", detail=None),
    )
    with pytest.raises(CloverOAuthRecoveryExhaustedError) as exc:
        store.get_token(_TENANT, _SOURCE)
    assert "X-Clover-Recovery-Available=true" in (exc.value.detail or "")


# -- terminal / fail-fast paths --------------------------------------------------------


def test_no_stored_record_is_not_connected() -> None:
    log: list[str] = []
    store, _, client = _store(log, stored=None)
    with pytest.raises(CloverOAuthNotConnectedError):
        store.get_token(_TENANT, _SOURCE)
    assert client.refreshed_with == []


def test_an_expired_refresh_token_fails_fast_without_any_network_call() -> None:
    # Neither leg can succeed once the refresh token is past its ~1-year expiry, and the
    # recovery token is strictly older. Two doomed requests would be pure latency.
    log: list[str] = []
    store, _, client = _store(
        log,
        stored=_record(previous="clvroar-0", access_exp_offset=60, refresh_exp_offset=-1),
    )
    with pytest.raises(CloverOAuthRecoveryExhaustedError):
        store.get_token(_TENANT, _SOURCE)
    assert log == ["read"]
    assert client.refreshed_with == []
    assert client.recovered_with == []


def test_a_transient_refresh_failure_propagates_and_does_not_recover() -> None:
    # A 5xx is retryable and says nothing about the token being spent; burning the recovery
    # credential on it would throw away the one-shot escape hatch.
    log: list[str] = []
    store, backend, client = _store(
        log,
        stored=_record(previous="clvroar-0", access_exp_offset=60),
        refresh_error=CloverOAuthTransientError("503"),
    )
    with pytest.raises(CloverOAuthTransientError):
        store.get_token(_TENANT, _SOURCE)
    assert client.recovered_with == []
    assert backend.writes == 0


def test_the_package_default_skew_is_far_below_the_access_token_lifetime() -> None:
    # The operator CLI forces rotation with a 365-day skew; that value lives only in
    # scripts/ and must never become the store's default. A skew at or above the token's
    # 30-minute life would rotate on EVERY call, burning Clover's capped live refresh
    # tokens and defeating D3 entirely.
    assert DEFAULT_REFRESH_SKEW.total_seconds() < ACCESS_TOKEN_LIFETIME_SECONDS / 2
    assert DEFAULT_REFRESH_SKEW == timedelta(minutes=5)
