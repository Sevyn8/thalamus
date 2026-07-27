"""Operator-run Clover sandbox OAuth driver (NOT part of the test suite).

Proves the full authorize -> exchange -> refresh -> recovery cycle against the LIVE Clover
sandbox, persisting to REAL Secret Manager so the D5 version lifecycle is exercised too — a
local file would prove rotation but nothing about pruning. Deliberately named without a
``test_`` prefix so pytest never collects it: it makes real network calls, writes real
credentials, and destroys real secret versions.

It runs under the OPERATOR's ADC, not the connector runtime SA, so
``secretmanager.versions.list`` / ``.destroy`` work today; granting them to the runtime SA is
a later terraform slice.

    gcloud auth application-default login
    uv run python connectors/clover-oauth/scripts/clover_sandbox_oauth.py \
        --project sevyn8-thalamus-staging <command>

``--project`` is REQUIRED and has no default: there must be no way to point this at
production by forgetting a flag.

Environment:

    CLOVER_CLIENT_ID    (required)  the Clover app id (public).
    CLOVER_APP_SECRET   (required)  the Clover app secret. Never pass on the command line.
    CLOVER_REDIRECT_URI (required for `authorize-url` / `exchange`) the registered callback.
    CLOVER_BASE_URL     (optional)  defaults to the NA sandbox host.

Typical run:

    ... authorize-url                    # open it, approve, copy the callback query string
    ... exchange --code X --merchant-id Y --employee-id Z
    ... show                             # confirm the record landed
    ... refresh                          # rotate; run twice to build a recovery credential
    ... show                             # previous_refresh_token is now populated
    ... simulate-lost-persist            # rotate and discard, reproducing a crashed persist
    ... recover                          # which generation does Clover actually accept?

That last pair is how the store's recovery ordering was settled: it tries the
just-rejected token before ``previous_refresh_token``, because a spent refresh token stays
valid as a RECOVERY token for ~2 weeks. CONFIRMED against the live sandbox (2026-07-27):
after ``simulate-lost-persist``, ``recover --token current`` returned ACCEPTED. The
commands remain for re-checking that behaviour against a future Clover change.

NO TOKEN VALUE IS EVER PRINTED. Only lengths, prefixes, and expiry times.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
from datetime import UTC, datetime, timedelta
from uuid import UUID

from thalamus_clover_oauth.client import SANDBOX_BASE_URL, CloverOAuthClient
from thalamus_clover_oauth.errors import CloverOAuthError
from thalamus_clover_oauth.naming import secret_id_for
from thalamus_clover_oauth.payload import CloverTokenSet
from thalamus_clover_oauth.token_store import CloverTokenStore
from thalamus_clover_oauth.vault import CloverTokenVault, GoogleSecretBackend

# Pinned so C2 inherits a working connection rather than a throwaway (decided in C1).
DEFAULT_TENANT_ID = "019f9d6d-c032-7e03-a232-ee77299f9b5d"  # TestCo
DEFAULT_SOURCE_ID = "clover_pos_v1"  # the analog of square_pos_v2

# A skew wider than the whole 30-minute access-token life, so `refresh` always takes the
# rotation branch instead of honouring the cache.
_FORCE_SKEW = timedelta(days=365)


def _redact(token: str) -> str:
    """A token's shape, never its value: enough to tell two tokens apart in a transcript."""
    return f"{token[:8]}...<{len(token)} chars>"


def _ts(epoch: int | None) -> str:
    if epoch is None:
        return "-"
    return f"{epoch} ({datetime.fromtimestamp(epoch, tz=UTC).isoformat()})"


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        print(f"[clover] {name} is not set")
        raise SystemExit(2)
    return value


def _client(args: argparse.Namespace, *, need_redirect: bool) -> CloverOAuthClient:
    base_url = os.environ.get("CLOVER_BASE_URL", SANDBOX_BASE_URL)
    redirect = os.environ.get("CLOVER_REDIRECT_URI", "")
    if need_redirect and not redirect:
        print("[clover] CLOVER_REDIRECT_URI is not set")
        raise SystemExit(2)
    client = CloverOAuthClient(
        base_url=base_url,
        client_id=_require_env("CLOVER_CLIENT_ID"),
        client_secret=_require_env("CLOVER_APP_SECRET"),
        redirect_uri=redirect,
    )
    print(f"[clover] base_url={base_url} environment={client.environment}")
    if client.environment != "sandbox":
        print("[clover] REFUSING: this driver is for the SANDBOX host only")
        raise SystemExit(2)
    return client


def _vault(args: argparse.Namespace) -> CloverTokenVault:
    print(f"[clover] project={args.project} tenant={args.tenant_id} source={args.source_id}")
    return CloverTokenVault(GoogleSecretBackend(project_id=args.project))


def _print_record(record: CloverTokenSet, *, label: str) -> None:
    print(f"[clover] {label}:")
    print(f"           merchant_id            {record.merchant_id}")
    print(f"           employee_id            {record.employee_id}")
    print(f"           environment            {record.environment}")
    print(f"           access_token           {_redact(record.access_token)}")
    print(f"           access_token_exp       {_ts(record.access_token_expiration)}")
    print(f"           refresh_token          {_redact(record.refresh_token)}")
    print(f"           refresh_token_exp      {_ts(record.refresh_token_expiration)}")
    previous = record.previous_refresh_token
    print(f"           previous_refresh_token {_redact(previous) if previous else '- (none yet)'}")
    print(f"           previous_rotated_at    {_ts(record.previous_rotated_at)}")
    print(f"           obtained_at            {_ts(record.obtained_at)}")


def cmd_authorize_url(args: argparse.Namespace) -> int:
    state = args.state or secrets.token_urlsafe(24)
    print(f"[clover] state={state}  (Clover echoes this back verbatim; check it matches)")
    print()
    print(_client(args, need_redirect=True).authorize_url(state=state))
    print()
    print("[clover] Open the URL, approve, then copy merchant_id/employee_id/code from the")
    print("[clover] callback query string into the `exchange` command.")
    print("[clover] NOTE: if the app is not installed on the merchant, Clover SILENTLY")
    print("[clover] diverts to the App Market listing instead of erroring.")
    return 0


def cmd_exchange(args: argparse.Namespace) -> int:
    client = _client(args, need_redirect=True)
    record = client.exchange_code(args.code, merchant_id=args.merchant_id, employee_id=args.employee_id)
    _vault(args).write(UUID(args.tenant_id), args.source_id, record)
    _print_record(record, label="exchanged and persisted")
    print("[clover] no previous_refresh_token yet: nothing has been rotated out.")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    tenant = UUID(args.tenant_id)
    print(f"[clover] secret_id={secret_id_for(tenant, args.source_id)}")
    record = _vault(args).read(tenant, args.source_id)
    if record is None:
        print("[clover] no stored record (never connected)")
        return 1
    _print_record(record, label="stored record")
    return 0


def cmd_refresh(args: argparse.Namespace) -> int:
    """Force a rotation regardless of skew, exercising the D2 persist-before-return path."""
    tenant = UUID(args.tenant_id)
    vault = _vault(args)
    before = vault.read(tenant, args.source_id)
    if before is None:
        print("[clover] no stored record; run `exchange` first")
        return 1
    # skew=0 alone would honour the 30-minute window; a skew larger than the token's whole
    # life forces the rotation branch every time.
    store = CloverTokenStore(vault=vault, client=_client(args, need_redirect=False), refresh_skew=_FORCE_SKEW)
    token = store.get_token(tenant, args.source_id)
    after = vault.read(tenant, args.source_id)
    assert after is not None
    print(f"[clover] returned access_token   {_redact(token)}")
    _print_record(after, label="record AFTER rotation")
    print(f"[clover] refresh_token rotated:  {before.refresh_token != after.refresh_token}")
    print(f"[clover] previous == the spent:  {after.previous_refresh_token == before.refresh_token}")
    return 0


def cmd_simulate_lost_persist(args: argparse.Namespace) -> int:
    """Rotate and DELIBERATELY DISCARD the result, reproducing a lost write.

    This is the only way to create the state the D4 recovery ordering exists for. After
    this the vault holds token N while Clover has already issued N+1 and killed N — exactly
    what a crash between rotate and persist leaves behind.

    DESTRUCTIVE AND INTENTIONALLY SO: if the follow-up `recover` then fails on every
    candidate, this merchant genuinely needs a fresh authorize. Sandbox only.
    """
    tenant = UUID(args.tenant_id)
    vault = _vault(args)
    record = vault.read(tenant, args.source_id)
    if record is None:
        print("[clover] no stored record; run `exchange` first")
        return 1
    client = _client(args, need_redirect=False)
    print("[clover] rotating and DISCARDING the result (simulating a crashed persist)...")
    discarded = client.refresh(
        record.refresh_token, merchant_id=record.merchant_id, employee_id=record.employee_id
    )
    print(f"[clover] Clover issued  {_redact(discarded.refresh_token)}  <- thrown away, as intended")
    print(f"[clover] vault still holds {_redact(record.refresh_token)}  <- now SPENT at Clover")
    print()
    print("[clover] The vault is now stale BY DESIGN. Next step, which is the experiment:")
    print("[clover]   recover --token current    (does Clover accept the token just spent?)")
    print("[clover]   recover --token previous   (the fallback, two generations back)")
    print("[clover]   recover                    (auto: current, then previous — the store's order)")
    return 0


def cmd_recover(args: argparse.Namespace) -> int:
    """Force the D4 recovery leg and REPORT WHICH CANDIDATE Clover accepts.

    The `--token` choice is what settled which generation Clover treats as
    recovery-eligible: a spent refresh token stays valid as a RECOVERY token for ~2 weeks,
    so after a lost persist the eligible one is the token just rejected (the record's
    CURRENT), not `previous`, which is two generations back. CONFIRMED against the live
    sandbox (2026-07-27): `--token current` returned ACCEPTED after a simulated lost persist.
    """
    tenant = UUID(args.tenant_id)
    vault = _vault(args)
    record = vault.read(tenant, args.source_id)
    if record is None:
        print("[clover] no stored record; run `exchange` first")
        return 1

    candidates: list[tuple[str, str]] = []
    if args.token in ("auto", "current"):
        candidates.append(("current", record.refresh_token))
    if args.token in ("auto", "previous"):
        if record.previous_refresh_token is None:
            if args.token == "previous":
                print("[clover] no previous_refresh_token stored; run `refresh` first")
                return 1
        else:
            candidates.append(("previous", record.previous_refresh_token))

    client = _client(args, need_redirect=False)
    for label, token in candidates:
        print(f"[clover] attempting recovery with the {label} token {_redact(token)} ...")
        try:
            recovered = client.recover(token, merchant_id=record.merchant_id, employee_id=record.employee_id)
        except CloverOAuthError as exc:
            print(f"[clover]   REJECTED: {type(exc).__name__}: {exc}")
            if exc.detail:
                print(f"[clover]   detail: {exc.detail}")
            continue

        print(f"[clover]   ACCEPTED -> Clover's recovery-eligible token is the {label.upper()} one")
        stamped = recovered.carrying_previous(
            spent_refresh_token=token, rotated_at=int(datetime.now(UTC).timestamp())
        )
        vault.write(tenant, args.source_id, stamped)
        _print_record(stamped, label="recovered and persisted")
        return 0

    print("[clover] every candidate was rejected; this merchant must re-consent")
    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Clover SANDBOX OAuth driver (operator-run)")
    parser.add_argument(
        "--project",
        required=True,
        help="GCP project holding the token vault. REQUIRED, no default: there must be no "
        "way to point this at production by forgetting a flag.",
    )
    parser.add_argument("--tenant-id", default=DEFAULT_TENANT_ID)
    parser.add_argument("--source-id", default=DEFAULT_SOURCE_ID)
    sub = parser.add_subparsers(dest="command", required=True)

    p_auth = sub.add_parser("authorize-url", help="print an authorize URL")
    p_auth.add_argument("--state", default=None, help="default: a fresh random token")
    p_auth.set_defaults(func=cmd_authorize_url)

    p_exch = sub.add_parser("exchange", help="exchange a pasted callback code")
    p_exch.add_argument("--code", required=True)
    p_exch.add_argument("--merchant-id", required=True)
    p_exch.add_argument("--employee-id", default=None)
    p_exch.set_defaults(func=cmd_exchange)

    sub.add_parser("show", help="print the stored record (redacted)").set_defaults(func=cmd_show)
    sub.add_parser("refresh", help="force a rotation").set_defaults(func=cmd_refresh)

    p_lost = sub.add_parser(
        "simulate-lost-persist",
        help="rotate and DISCARD the result, reproducing a crashed persist (destructive)",
    )
    p_lost.set_defaults(func=cmd_simulate_lost_persist)

    p_rec = sub.add_parser("recover", help="force the recovery leg and report which token wins")
    p_rec.add_argument(
        "--token",
        choices=("auto", "current", "previous"),
        default="auto",
        help="which candidate to present. auto (default) tries current then previous, the "
        "same order the token store uses.",
    )
    p_rec.set_defaults(func=cmd_recover)

    args = parser.parse_args()
    try:
        result: int = args.func(args)
        return result
    except CloverOAuthError as exc:
        print(f"[clover] FAILED: {type(exc).__name__}: {exc}")
        if exc.detail:
            print(f"[clover] detail: {exc.detail}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
