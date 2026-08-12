"""The sender's Terraform module, checked from its own suite.

A NEW MODULE STARTS LIFE UNGUARDED, WHICH IS THE REASON THIS FILE EXISTS ON DAY ONE. Slice 5d
shipped an env var the module never wired and a write path sat dead in staging for two days
behind a green apply. synapse-ui-server has a test that parses its own module for exactly that,
and that test is why 5d cannot recur on that service. A second service without one would start
from the position 5d was in.

WHY IT LIVES HERE AND NOT NEXT TO synapse-ui-server's COPY. Each test parses ITS OWN module. A
shared test over both would need a list of modules, which is the same class of thing as a root
list or a regex: correct until the next module, and nothing reports the day it stops being.
Colocated, a module without a posture test is a service without a test directory, which is
visible; a module missing from a shared list is not.

THESE PARSE TEXT, AND THAT IS THE POINT. `terraform validate` proves the configuration parses; it
proves nothing about whether a grant is ordered before the revision that needs it, because both
orderings are valid Terraform. The ordering is a property of one list.
"""

from __future__ import annotations

import re
from pathlib import Path

# tests -> axon-sender -> services -> axon -> the monorepo root
_REPO_ROOT = Path(__file__).resolve().parents[4]
_MODULE = _REPO_ROOT / "infra" / "modules" / "cloud-run-service-axon-sender" / "main.tf"

# Every principal that means "anyone on the internet". Two spellings, both live.
_ANONYMOUS = ("allUsers", "allAuthenticatedUsers")


def _module_text() -> str:
    return _MODULE.read_text(encoding="utf-8")


def _terraform_code() -> str:
    """The module with comment lines stripped, so prose about a thing is not read as the thing.

    Every check below asks whether a STRING APPEARS IN THE CONFIGURATION. The comments in that
    file discuss `allUsers` at length in order to explain why it is absent, so scanning the raw
    text would report the explanation as the violation. Same shape as synapse-ui-server's
    equivalent, and the same reason a guard that names what it forbids cannot scan itself.
    """
    return "\n".join(line for line in _module_text().splitlines() if not line.strip().startswith("#"))


def test_the_module_is_where_this_test_thinks_it_is() -> None:
    """THE VACUITY GUARD. Every check below reads this file; a path that stopped resolving would
    make all of them pass against an empty string."""
    assert _MODULE.is_file(), f"{_MODULE} not found"
    assert "google_cloud_run_v2_service" in _module_text()


def test_every_secret_iam_member_is_listed_in_the_services_depends_on() -> None:
    """SLICE 5d, REFUSED IN ADVANCE ON A SERVICE THAT DID NOT EXIST WHEN 5d HAPPENED.

    THE FAILURE THIS CATCHES. The env blocks reference
    ``data.google_secret_manager_secret.*.secret_id``, which is the DATA SOURCE. Terraform sees an
    edge to the data source and NO EDGE AT ALL to the ``secret_iam_member``, so it is free to
    create the revision before the grant exists or propagates. The container then cannot read its
    own credential, and every value this service needs is required at startup, so the result is a
    failed health check while nothing in the plan says a thing.

    ``depends_on`` is the fix and it is invisible: a list somebody has to remember to extend when
    they add a secret, in a file where the addition looks complete without it.

    PARSED FROM THE MODULE rather than hardcoded, so a third secret is covered the day it lands.
    """
    code = _terraform_code()

    declared = set(re.findall(r'resource\s+"google_secret_manager_secret_iam_member"\s+"([a-z0-9_]+)"', code))
    assert declared, "parsed zero secret iam_members; the regex has stopped biting"

    depends_block = re.search(r"depends_on\s*=\s*\[(.*?)\]", code, re.DOTALL)
    assert depends_block is not None, (
        "the Cloud Run service has no depends_on at all. Every secret grant in this module must "
        "be listed there, or a revision can be created before it can read its own DSN."
    )
    listed = set(re.findall(r"google_secret_manager_secret_iam_member\.([a-z0-9_]+)", depends_block.group(1)))

    missing = sorted(declared - listed)
    assert not missing, (
        f"these secret grants are not in the service's depends_on: {missing}. Terraform will not "
        "infer the ordering, because the env blocks reference the DATA SOURCE and not the grant."
    )


def test_the_subscriber_grant_is_also_in_the_depends_on() -> None:
    """THE SAME ORDERING HAZARD ON A GRANT THAT IS NOT A SECRET, and it is worse here.

    The service's startup check calls ``get_subscription`` and RAISES if the subscription is
    unreachable, so a revision created before the subscriber binding propagates does not merely
    fail to read something later: it refuses to start. That is the loud failure and it is the
    right one, but the ordering makes it not happen at all.

    5d's test covers secrets because secrets were what 5d was about. This service's credentials
    are not all secrets, so covering only those would inherit the shape of the old bug rather
    than the lesson.
    """
    code = _terraform_code()

    declared = set(re.findall(r'resource\s+"google_pubsub_subscription_iam_member"\s+"([a-z0-9_]+)"', code))
    assert declared, "parsed zero pubsub subscription iam_members; the regex has stopped biting"

    depends_block = re.search(r"depends_on\s*=\s*\[(.*?)\]", code, re.DOTALL)
    assert depends_block is not None
    listed = set(re.findall(r"google_pubsub_subscription_iam_member\.([a-z0-9_]+)", depends_block.group(1)))

    missing = sorted(declared - listed)
    assert not missing, (
        f"these subscription grants are not in the service's depends_on: {missing}. The revision "
        "can be created before the binding propagates, and this service refuses to start when it "
        "cannot reach its subscription."
    )


def test_the_service_is_not_anonymously_invokable() -> None:
    """NO allUsers, NO allAuthenticatedUsers, ANYWHERE IN THE CONFIGURATION.

    Every HTTP service in this estate except Synapse's carries an ``allUsers`` binding on
    ``roles/run.invoker``, which is a standing HIGH finding. This service has no callers at all:
    its work is an outbound pull and the only inbound request is Cloud Run's own health probe,
    which is not subject to either control. So the binding would buy nothing and expose the
    process to the internet.
    """
    code = _terraform_code()
    found = [principal for principal in _ANONYMOUS if principal in code]
    assert found == [], (
        f"{found} appears in the module's executable configuration. This service has no callers; "
        "if that has changed it needs its own commit and a stated reason, not a line inside "
        "another change."
    )


def test_the_service_has_no_invoker_binding_at_all() -> None:
    """THE STRONGER FORM OF THE CHECK ABOVE, and the one that actually holds today.

    A service with NO ``run.invoker`` member cannot be called by anyone, named principal or not.
    The test above refuses the two anonymous spellings; this refuses the whole resource type, so
    a binding to a specific service account also has to be argued for rather than added.
    """
    code = _terraform_code()
    assert "google_cloud_run_v2_service_iam" not in code, (
        "an invoker binding appeared on axon-sender. Nothing calls this service: it pulls a "
        "queue and answers a health probe. A binding means somebody expects to call it, which "
        "is a design change rather than a configuration one."
    )


def test_min_instances_cannot_be_zero() -> None:
    """THE PRECONDITION, ASSERTED AS EXISTING RATHER THAN TRUSTED.

    At ``min_instances = 0`` the pull loop scales away and the queue stops draining, and NOTHING
    WAKES IT: the work is an outbound pull, so there is no inbound request to trigger a cold
    start. The backlog would grow silently until somebody noticed the message-age alert, which is
    a slow way to discover a stopped consumer.

    The ``lifecycle.precondition`` is the primary control because it fails ``terraform plan``,
    which stops an apply that this test would only catch if somebody ran it. This asserts the
    precondition still exists, in a repo with no CI, for the same reason synapse-ui-server's
    equivalent does.
    """
    code = _terraform_code()
    assert "precondition" in code, (
        "the lifecycle.precondition on min_instances is gone. It is the plan-time half of this "
        "guard and there is no CI to run the pytest half."
    )
    assert "min_instances >= 1" in code, (
        "the precondition no longer asserts min_instances >= 1; check it still asserts what it "
        "claims rather than having been softened to something that always passes."
    )


def test_the_pull_loop_keeps_its_cpu() -> None:
    """``cpu_idle = false``, because the default throttles a background loop.

    Cloud Run allocates CPU only during a request by default. This service's real work happens
    between requests, so at the default the loop runs at whatever rate the health probe happens
    to wake it: the queue still drains, at a rate nobody chose and nothing reports. That is the
    quietest of the failures in this file, which is why it is checked rather than commented.
    """
    code = _terraform_code()
    assert re.search(r"cpu_idle\s*=\s*false", code), (
        "cpu_idle is not false. The pull loop is a background task and Cloud Run throttles CPU "
        "between requests by default, so the queue would drain at an unpredictable rate."
    )
