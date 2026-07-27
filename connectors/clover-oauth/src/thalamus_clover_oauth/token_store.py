"""The Clover token store: read, rotate-if-stale, PERSIST, then return (D2/D3/D4).

PLACEMENT ASYMMETRY WITH THE SQUARE LANE, DELIBERATE. Square's equivalent
(``VaultTokenStore``) lives in the CONNECTOR package, not in ``square-oauth``. Here the
store lives in the OAuth package, because on Clover the read-path ordering is not a detail
of the connector — it is the thing that keeps a merchant connected, and it must exist and be
proven before any connector does. C2 may move it if a second consumer appears; until then
this is where the policy lives.

WHY THE ORDERING IS LOAD-BEARING. Square's refresh is NON-DESTRUCTIVE: the code flow hands
back the same refresh token, so a crash between rotating and persisting costs one wasted
round trip and the next run simply refreshes again. Square's own store persists before
returning too, but nothing breaks there if it did not.

Clover's refresh is SINGLE-USE. The instant Clover answers ``/oauth/v2/refresh``, the token
we sent is dead and a new one exists ONLY in our process memory. A crash before that lands
in Secret Manager leaves the vault holding a token Clover has already invalidated — the
merchant is disconnected and nobody finds out until the next run fails. Hence:

    1. read the record
    2. access token valid within skew  ->  USE IT, WRITE NOTHING            (D3)
    3. otherwise POST /oauth/v2/refresh                                      (destructive)
    4. PERSIST the new pair, stamped with the token just spent, BEFORE use   (D2)
    5. only then return it

Step 4 strictly precedes step 5. The window between 3 and 4 is irreducible — it is the one
place a crash still costs something — and that residual risk is exactly what
``previous_refresh_token`` and the recovery leg (D4) exist to cover.

CACHING (D3). Step 2 returns without writing even though a 30-minute access token means a
scheduled run will usually rotate anyway. It costs nothing (the same single write per
rotation) and it collapses a burst — retries, a multi-domain trigger, an operator poking
the CLI — into one rotation instead of several, which matters because Clover caps the number
of live refresh tokens per app per merchant.

CONCURRENCY. No lock, and unlike Square last-writer-wins is NOT safe here: two concurrent
rotations produce two chains and one of them is dead. Today the connector runs one trigger
per process (the Cloud Run Job model), so concurrent rotation for one merchant does not
arise. A future long-lived or parallel transport MUST add a lock or a compare-and-set on the
secret version before running two of these against one merchant.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID

from dis_core.logging import get_logger
from thalamus_clover_oauth.client import CloverOAuthClient
from thalamus_clover_oauth.errors import (
    CloverOAuthNotConnectedError,
    CloverOAuthRecoveryExhaustedError,
    CloverOAuthRefreshRejectedError,
)
from thalamus_clover_oauth.payload import CloverTokenSet
from thalamus_clover_oauth.vault import CloverTokenVault

_SERVICE = "thalamus-clover-oauth"
_log = get_logger(_SERVICE)

# Rotate this long before the access token actually expires. Clover access tokens live 30
# minutes (measured), so a 5-minute skew leaves a comfortable margin for a slow pull while
# still using most of each token's life.
DEFAULT_REFRESH_SKEW = timedelta(minutes=5)


def _default_clock() -> datetime:
    return datetime.now(UTC)


class CloverTokenStore:
    """Secret Manager-backed Clover access-token resolution for one (tenant, source)."""

    def __init__(
        self,
        *,
        vault: CloverTokenVault,
        client: CloverOAuthClient,
        refresh_skew: timedelta = DEFAULT_REFRESH_SKEW,
        clock: Callable[[], datetime] = _default_clock,
    ) -> None:
        self._vault = vault
        self._client = client
        self._refresh_skew = refresh_skew
        self._clock = clock

    def get_token(self, tenant_id: UUID, source_id: str) -> str:
        """A usable Clover access token, rotating and persisting first if required."""
        log = _log.bind(stage="token_store", tenant_id=str(tenant_id), source_id=source_id)

        # 1. read
        current = self._vault.read(tenant_id, source_id)
        if current is None:
            raise CloverOAuthNotConnectedError(
                "no Clover OAuth record for this source; the merchant has not connected"
            )

        # 2. still valid within skew -> use it, write nothing (D3)
        now = self._clock()
        if not current.needs_refresh(now=now, skew=self._refresh_skew):
            return current.access_token

        # Neither leg can succeed once the refresh token itself has expired (~1 year), and
        # the recovery token is strictly older. Fail fast rather than burn two requests.
        if current.refresh_token_expired(now=now):
            raise CloverOAuthRecoveryExhaustedError(
                "the stored Clover refresh token is past its expiry; the merchant must re-consent",
                detail=f"refresh_token_expiration={current.refresh_token_expiration}",
            )

        # 3. rotate. DESTRUCTIVE: on return, current.refresh_token is dead.
        try:
            rotated = self._client.refresh(
                current.refresh_token,
                merchant_id=current.merchant_id,
                employee_id=current.employee_id,
            )
        except CloverOAuthRefreshRejectedError as exc:
            # The expected shape of a lost write: our stored token was already spent.
            log.warning("Clover rejected the refresh; attempting recovery (D4)")
            return self._recover(tenant_id, source_id, current, rejected=exc)

        # 4. PERSIST before use, stamping the token we just spent as the recovery credential
        # 5. only then return
        return self._persist_then_return(tenant_id, source_id, rotated, spent=current.refresh_token, now=now)

    def _recover(
        self,
        tenant_id: UUID,
        source_id: str,
        current: CloverTokenSet,
        *,
        rejected: CloverOAuthRefreshRejectedError,
    ) -> str:
        """D4: restore the chain, trying the just-rejected token FIRST, then the previous one.

        THE ORDER MATTERS, and it is not the obvious one. A spent refresh token is invalid
        as a REFRESH token but stays valid as a RECOVERY token for ~2 weeks: the same string
        in two roles. Trace the failure this exists for:

            record holds N -> we refresh with N -> Clover rotates (N spent, N+1 issued)
            -> our persist FAILS -> next run reads N -> refresh with N -> 401.

        At that instant the recovery-eligible token is N — the very one we just presented.
        ``previous_refresh_token`` is N-1, two generations back, and should be rejected. So
        the record's CURRENT token is attempt 1 and ``previous_refresh_token`` is attempt 2.

        CONFIRMED against the live Clover sandbox (2026-07-27): after a simulated lost
        persist, recovery with the just-rejected current token was ACCEPTED.

        Which attempt succeeds is itself diagnostic and is logged: the current token winning
        means the ROTATION landed and our PERSIST was lost; the previous one winning means
        the rotation itself never took effect. Those point at different bugs.

        The attempts are NOT gated on ``X-Clover-Recovery-Available``. The asymmetry settles
        it: attempting when unavailable costs one failed HTTP call and a clean terminal
        error, while skipping a valid recovery costs the merchant. The header's value is
        carried into the terminal error's detail for diagnosis.
        """
        log = _log.bind(stage="token_store", tenant_id=str(tenant_id), source_id=source_id)

        # (label, token) in attempt order. The label is what gets logged on success.
        candidates: list[tuple[str, str]] = [("current", current.refresh_token)]
        if current.previous_refresh_token is not None:
            candidates.append(("previous", current.previous_refresh_token))

        last_detail = rejected.detail
        for label, token in candidates:
            try:
                recovered = self._client.recover(
                    token, merchant_id=current.merchant_id, employee_id=current.employee_id
                )
            except CloverOAuthRecoveryExhaustedError as exc:
                # The recovery response's detail is the more informative of the two: it
                # carries the recovery-availability header where Clover sent one.
                last_detail = exc.detail or last_detail
                continue

            # Which candidate won says WHICH failure happened, so name it in the log.
            diagnosis = (
                "the rotation landed and our persist was lost"
                if label == "current"
                else "the rotation itself did not take effect"
            )
            log.warning(
                f"Clover recovery succeeded using the {label} refresh token; the chain was "
                f"restored ({diagnosis})"
            )
            # Same persist-before-return discipline: recovery is a rotation too, and the
            # token we just presented becomes the new recovery credential.
            return self._persist_then_return(tenant_id, source_id, recovered, spent=token, now=self._clock())

        raise CloverOAuthRecoveryExhaustedError(
            "Clover rejected the refresh and every recovery candidate "
            f"({', '.join(label for label, _ in candidates)}); the merchant must re-consent",
            detail=last_detail,
        ) from rejected

    def _persist_then_return(
        self,
        tenant_id: UUID,
        source_id: str,
        rotated: CloverTokenSet,
        *,
        spent: str,
        now: datetime,
    ) -> str:
        """Stamp the spent token as the recovery credential, PERSIST, then return (D2 step 4/5).

        Nothing may be inserted between the write and the return. If the write raises, the
        exception propagates and the caller never sees a token that is not durable — better
        a failed run than a used-but-unpersisted rotation, which is the one state that
        silently disconnects a merchant.
        """
        record = rotated.carrying_previous(spent_refresh_token=spent, rotated_at=int(now.timestamp()))
        self._vault.write(tenant_id, source_id, record)
        return record.access_token
