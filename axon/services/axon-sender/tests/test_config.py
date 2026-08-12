"""The boot guard: what the sender refuses to start without, and what it refuses to hold.

FAILING AT BOOT IS THE WHOLE POINT. A misconfigured revision that started would pull messages it
cannot send and nack them until they dead-letter, and the DLQ would then report a delivery
problem that is actually a typo. This is the difference between a revision that never becomes
ready and a lane full of dead letters with a misleading cause.
"""

from __future__ import annotations

import os

import pytest
from axon_sender.config import SUBSCRIPTION, load_config

_BASE = {
    "GOOGLE_CLOUD_PROJECT": "sevyn8-thalamus-staging",
    "AXON_SENDER_URL": "postgresql+psycopg://a@h/d",
    "AXON_SENDGRID_API_KEY": "test-key",
    "AXON_SENDGRID_FROM_EMAIL": "noreply@test.invalid",
}


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch):  # type: ignore[no-untyped-def]
    """Run under EXACTLY the given environment and nothing else.

    os.environ IS REPLACED WHOLESALE rather than the named variables set. A developer with one of
    these exported would otherwise make the missing-variable cases pass locally and fail in Cloud
    Run, which is the difference these tests exist to close.
    """

    def under(values: dict[str, str]) -> None:
        monkeypatch.setattr(os, "environ", dict(values))

    return under


def test_a_complete_environment_loads(env) -> None:  # type: ignore[no-untyped-def]
    """THE VACUITY GUARD for every refusal below. A loader that refused everything would make
    them all pass while the service could never start at all."""
    env(_BASE)

    config = load_config()

    assert config.project_id == "sevyn8-thalamus-staging"
    assert config.expected_database == "thalamus"


@pytest.mark.parametrize("name", sorted(_BASE))
def test_every_variable_is_required(env, name: str) -> None:  # type: ignore[no-untyped-def]
    """PARAMETRISED SO THE FAILURE NAMES THE VARIABLE rather than saying one of four is missing.

    Each of these has a distinct consequence and none is optional: no project means no
    subscription path, no DSN means no ledger, no key or from-address means every send is refused
    per message at runtime in a way that reads like a provider outage.
    """
    env({key: value for key, value in _BASE.items() if key != name})

    with pytest.raises(RuntimeError, match=name):
        load_config()


def test_the_error_names_every_missing_variable_at_once(env) -> None:  # type: ignore[no-untyped-def]
    """ALL AT ONCE, NOT THE FIRST. An operator fixing one and redeploying to discover the next is
    four deploys where one would do."""
    env({})

    with pytest.raises(RuntimeError) as caught:
        load_config()

    message = str(caught.value)
    for name in _BASE:
        assert name in message


def test_the_reader_credential_is_refused(env) -> None:  # type: ignore[no-untyped-def]
    """THE SENDER MUST NOT HOLD THE READ CREDENTIAL, AND THE REFUSAL IS THE SIGN ON THE WALL.

    axon_reader holds SELECT on both delivery ledgers. A sender holding it could read back a
    ledger of who was contacted about what, which is exactly the exposure the read-nothing design
    buys by having axon_sender hold INSERT and no SELECT anywhere.

    THE GRANT IS THE ACTUAL WALL. This refusal cannot stop somebody putting the reader's DSN in
    the sender's secret; it stops the much likelier version, where the variable is set because it
    was copied from the console's configuration.
    """
    env({**_BASE, "AXON_READER_URL": "postgresql+psycopg://r@h/d"})

    with pytest.raises(RuntimeError, match="AXON_READER_URL"):
        load_config()


def test_the_subscription_name_is_not_configurable() -> None:
    """ONE NAME, IN ONE PLACE. The topic's name lives in axon.envelope because both sides need
    it; the subscription's lives here because only this side does. Neither is an env var, because
    a queue name that can drift per environment is a queue somebody eventually points at the
    wrong lane, and the failure is a consumer draining nothing while reporting healthy."""
    assert SUBSCRIPTION == "axon-send-requested-sub"
