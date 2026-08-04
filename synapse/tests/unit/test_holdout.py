"""Holdout assignment. Pure, and the most important test here runs in a SEPARATE PROCESS.

THE PYTHONHASHSEED TRAP IS THE REASON THIS FILE EXISTS. Python randomises string hashing per
process, so ``hash(subject) % 100`` returns a different bucket in every interpreter run: a SKU
treated on Monday would be held out on Tuesday and treated again on Wednesday. Nothing raises,
and no test that runs entirely inside one process can see it — every in-process assertion about
stability would pass while the property was comprehensively broken.

So ``test_assignment_is_stable_across_processes`` shells out to a fresh interpreter, with an
explicitly DIFFERENT PYTHONHASHSEED, and compares. That is the one test that would actually fail
if someone swapped sha256 back for hash().
"""

from __future__ import annotations

import subprocess
import sys
from dataclasses import FrozenInstanceError

import pytest

from synapse.core.analysis import DEAD_STOCK
from synapse.core.holdout import Arm, Holdout, assign

HOLDOUT = Holdout(
    unit=("tenant_id", "store_id", "sku_id"),
    holdout_percent=20,
    salt="test-salt",
    fitted=False,
    stands_in_for="a test",
)


def _subject(sku: str) -> tuple[str, str, str]:
    return ("tenant-1", "store-1", sku)


# ---------------------------------------------------------------------------
# Stability — the property the whole design rests on
# ---------------------------------------------------------------------------


def test_assignment_is_stable_within_a_process() -> None:
    """Necessary and nowhere near sufficient — see the module docstring."""
    first = [assign(HOLDOUT, _subject(f"SKU-{i}")) for i in range(50)]
    second = [assign(HOLDOUT, _subject(f"SKU-{i}")) for i in range(50)]
    assert first == second


def test_assignment_is_stable_across_processes() -> None:
    """THE TEST THAT CATCHES hash().

    Runs the same assignment in a fresh interpreter under a DIFFERENT PYTHONHASHSEED. With
    sha256 the answer is identical; with ``hash()`` it would differ on essentially every run,
    and the in-process test above would still pass while the experiment was noise.
    """
    subjects = [_subject(f"SKU-{i}") for i in range(200)]
    here = [assign(HOLDOUT, subject).value for subject in subjects]

    program = (
        "import sys;"
        "sys.path.insert(0, 'src');"
        "from synapse.core.holdout import Holdout, assign;"
        "h = Holdout(unit=('tenant_id','store_id','sku_id'), holdout_percent=20,"
        " salt='test-salt', fitted=False, stands_in_for='a test');"
        "print(','.join(assign(h, ('tenant-1','store-1', f'SKU-{i}')).value for i in range(200)))"
    )
    result = subprocess.run(  # noqa: S603 - fixed argv, no shell, no user input
        [sys.executable, "-c", program],
        capture_output=True,
        text=True,
        check=True,
        cwd=_synapse_root(),
        env={"PYTHONHASHSEED": "12345", "PATH": "/usr/bin:/bin"},
    )
    there = result.stdout.strip().split(",")

    assert there == here, (
        "assignment differs between processes. If sha256 was replaced with hash(), every "
        "subject is reassigned on every run and the experiment is noise with a label on it"
    )


def _synapse_root() -> str:
    import pathlib

    return str(pathlib.Path(__file__).resolve().parents[2])


def test_a_different_salt_reshuffles() -> None:
    """The salt has to matter, or it is not doing the job the design gives it."""
    other = Holdout(unit=HOLDOUT.unit, holdout_percent=20, salt="different", fitted=False, stands_in_for="x")
    subjects = [_subject(f"SKU-{i}") for i in range(200)]
    assert [assign(HOLDOUT, s) for s in subjects] != [assign(other, s) for s in subjects]


def test_the_split_is_roughly_the_declared_percent() -> None:
    """Not a distribution test — a sanity check that the modulo maps to the percent at all.

    A wide band on purpose: this must not fail because of ordinary sampling variation, only
    because the arithmetic is wrong (an inverted comparison, a wrong bucket count, a digest that
    is not well distributed).
    """
    subjects = [_subject(f"SKU-{i}") for i in range(2000)]
    held = sum(assign(HOLDOUT, s) is Arm.HOLDOUT for s in subjects)
    assert 250 <= held <= 550, f"{held}/2000 held out at holdout_percent=20"


def test_both_arms_are_reachable() -> None:
    """A guard that would catch an inverted comparison producing one arm for everybody."""
    arms = {assign(HOLDOUT, _subject(f"SKU-{i}")) for i in range(200)}
    assert arms == {Arm.TREATMENT, Arm.HOLDOUT}


def test_the_separator_prevents_a_collision_between_different_subjects() -> None:
    """("ab","c") and ("a","bc") must not assign identically. Without a separator they would
    concatenate to the same key, and two distinct subjects would silently share an arm.

    TESTED THROUGH ``assign``, not by reimplementing the key here — a test that rebuilds the
    thing it is testing passes whenever the two copies agree, including when both are wrong.
    Observable consequence instead: across pairs that WOULD concatenate identically, a correct
    separator makes roughly half of them land in different arms, and a missing one makes ALL of
    them land in the same arm. One differing pair is enough to prove the separator is there.
    """
    two_column = Holdout(unit=("a", "b"), holdout_percent=50, salt="s", fitted=False, stands_in_for="x")
    colliding_pairs = [((f"x{i}y", "z"), (f"x{i}", "yz")) for i in range(40)]
    differing = [
        pair for pair in colliding_pairs if assign(two_column, pair[0]) != assign(two_column, pair[1])
    ]
    assert differing, (
        "every subject pair that concatenates identically also assigns identically, which is "
        "what a missing separator looks like"
    )


# ---------------------------------------------------------------------------
# The constructor
# ---------------------------------------------------------------------------


def test_a_holdout_of_zero_or_a_hundred_percent_is_refused() -> None:
    for percent in (0, 100, -1, 101):
        with pytest.raises(ValueError, match="1..99"):
            Holdout(unit=("sku_id",), holdout_percent=percent, salt="s", fitted=True, stands_in_for=None)


def test_an_unfitted_percent_must_say_what_it_stands_in_for() -> None:
    """Same one-way discipline as Threshold, and for the same reason: a comment cannot be
    enforced but a constructor can."""
    with pytest.raises(ValueError, match="stands in for"):
        Holdout(unit=("sku_id",), holdout_percent=20, salt="s", fitted=False, stands_in_for=None)


def test_a_fitted_percent_must_not_claim_to_substitute() -> None:
    with pytest.raises(ValueError, match="stands in for nothing"):
        Holdout(unit=("sku_id",), holdout_percent=20, salt="s", fitted=True, stands_in_for="a guess")


def test_an_empty_salt_is_refused() -> None:
    with pytest.raises(ValueError, match="explicit salt"):
        Holdout(unit=("sku_id",), holdout_percent=20, salt="", fitted=True, stands_in_for=None)


def test_a_subject_of_the_wrong_width_is_refused() -> None:
    """Assignment over the wrong key would be silent and stable — the worst combination."""
    with pytest.raises(ValueError, match="wrong key"):
        assign(HOLDOUT, ("tenant-1", "store-1"))


def test_there_is_no_unassigned_arm() -> None:
    """A third value would let an unanalysable action exist while looking deliberate."""
    assert {arm.value for arm in Arm} == {"treatment", "holdout"}


def test_the_holdout_is_frozen() -> None:
    with pytest.raises(FrozenInstanceError):
        HOLDOUT.holdout_percent = 50  # type: ignore[misc]


# ---------------------------------------------------------------------------
# The declaration's own holdout
# ---------------------------------------------------------------------------


def test_dead_stock_assigns_per_sku_over_its_full_grain() -> None:
    """Per-STORE would be the cleaner comparison and is unusable at two stores."""
    holdout = DEAD_STOCK.holdout
    assert holdout is not None
    assert holdout.unit == DEAD_STOCK.grain
    assert "sku_id" in holdout.unit


def test_dead_stocks_holdout_admits_it_is_unfitted_and_says_why_that_matters() -> None:
    """D6 one layer up. The reason must name the CONSEQUENCE — that an empty treated arm is what
    underpowered looks like — because someone will otherwise read it as a bug."""
    holdout = DEAD_STOCK.holdout
    assert holdout is not None
    assert holdout.fitted is False
    assert holdout.stands_in_for is not None
    assert "power calculation" in holdout.stands_in_for
    assert "ZERO treated actions" in holdout.stands_in_for
