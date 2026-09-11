"""The pre-apply check must validate the aggregations the module actually uses.

``infra/modules/monitoring-alerts/verify-aggregations.sh`` calls timeSeries.list with each
policy's aligner, reducer and alignment period to confirm the API accepts them BEFORE an apply —
the check that catches these rejections before they reach an apply.

IT RESTATES THOSE VALUES, so it can drift from the module it is checking. A drifted checker is
worse than none: it passes, and it passed against a combination nothing deploys. That is the same
shape as a guard whose scope does not match its claim, so the agreement is a test rather than a
convention.
"""

from __future__ import annotations

import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3] / "infra" / "modules" / "monitoring-alerts"
_TF = _ROOT / "main.tf"
_SH = _ROOT / "verify-aggregations.sh"


def _module_aggregations() -> dict[str, tuple[str, str, str]]:
    """(aligner, reducer, alignment_period) per policy, read from the terraform."""
    body = _TF.read_text(encoding="utf-8")
    out: dict[str, tuple[str, str, str]] = {}
    parts = re.split(r'resource "google_monitoring_alert_policy" "(\w+)"', body)
    for i in range(1, len(parts), 2):
        name, chunk = parts[i], parts[i + 1].split("\nresource ")[0]
        aligner = re.search(r'per_series_aligner\s*=\s*"(\w+)"', chunk)
        reducer = re.search(r'cross_series_reducer\s*=\s*"(\w+)"', chunk)
        align = re.search(r'alignment_period\s*=\s*"(\w+)"', chunk)
        assert aligner and align, f"{name} has no aligner or alignment period"
        out[name] = (aligner.group(1), reducer.group(1) if reducer else "", align.group(1))
    return out


def _script_aggregations() -> dict[str, tuple[str, str, str]]:
    """The same triples as restated in the shell script's POLICIES array."""
    out: dict[str, tuple[str, str, str]] = {}
    for line in _SH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line.startswith('"') or line.count("|") != 4:
            continue
        name, _metric, aligner, reducer, align = line.strip('"').split("|")
        out[name] = (aligner, reducer, align.rstrip('"'))
    return out


def test_both_files_are_where_this_test_thinks_they_are() -> None:
    """Vacuity guard: two path-based reads, and a rename would make every comparison below
    compare two empty dicts and pass."""
    assert _TF.is_file(), f"{_TF} not found"
    assert _SH.is_file(), f"{_SH} not found"
    assert len(_module_aggregations()) >= 6, "parsed fewer than six policies; the regex stopped biting"
    assert len(_script_aggregations()) >= 6, "parsed fewer than six script rows; the parser stopped biting"


def test_the_script_checks_every_policy_the_module_defines() -> None:
    """A policy added to the module and not to the script deploys without ever being pre-checked —
    which is how the next rejection arrives at apply time instead of before it."""
    missing = sorted(set(_module_aggregations()) - set(_script_aggregations()))
    assert not missing, f"policies in the module with no pre-apply check: {missing}"


def test_the_script_checks_nothing_the_module_does_not_define() -> None:
    """The other direction. A stale row validates a combination nothing deploys and reports
    ACCEPTED, which reads as coverage."""
    extra = sorted(set(_script_aggregations()) - set(_module_aggregations()))
    assert not extra, f"pre-apply check validates policies that do not exist: {extra}"


def test_every_aggregation_triple_agrees() -> None:
    """THE ONE THAT MATTERS. Aligner, reducer and alignment period must match exactly.

    All three are load-bearing and each has already been rejected by the API in this module:
    ALIGN_MAX on a DELTA+DISTRIBUTION metric, REDUCE_MAX on a distribution-valued aligner output,
    and a 93600s alignment period against a 90000s ceiling.
    """
    module, script = _module_aggregations(), _script_aggregations()
    disagreements = [
        f"{name}: module={module[name]} script={script[name]}"
        for name in sorted(set(module) & set(script))
        if module[name] != script[name]
    ]
    assert not disagreements, (
        "the pre-apply check would validate a different aggregation than the module deploys: "
        + "; ".join(disagreements)
    )


def test_no_alignment_period_exceeds_the_known_ceiling() -> None:
    """90000s (25h) is the alert-policy alignment ceiling, discovered by an API rejection.

    Asserted across ALL policies rather than the one that broke: a constraint belongs to the
    FIELD, and fixing only the instance being thought about is how 93600s survived a round of
    careful reasoning about exactly this limit on a sibling policy.
    """
    ceiling = 90000
    over = {
        name: align
        for name, (_a, _r, align) in _module_aggregations().items()
        if int(align.rstrip("s")) > ceiling
    }
    assert not over, f"alignment_period above the {ceiling}s ceiling: {over}"
