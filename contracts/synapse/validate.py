#!/usr/bin/env python3
"""Conformance harness for the Synapse capability + signal contracts.

Deliberately the SAME SHAPE as contracts/conformance/validate.py (the C6 pack
harness): check_schema first, a check() accumulator printing [PASS]/[FAIL], positive
fixture validation, negative cases that each name the mistake they guard, and a scope
guard asserting what must be ABSENT. Pure validation — no service, no loader, no DB.

Run: python3 contracts/synapse/validate.py

DIFFERENCE FROM THE C6 HARNESS, and it is deliberate: there are no content digests
here. The pack contract signs and digests a distributed artifact; a capability
descriptor is a declaration checked in the repo, so a digest would be ceremony with
nothing to protect against. Copying it for symmetry would be exactly the kind of
inherited-without-reason structure this project keeps having to unpick.

This harness is invoked two ways, because THIS REPO HAS NO CI: by
synapse/tests/unit/test_contracts_conformance.py (so `make test` covers it) and by
`make -C synapse conformance`. The C6 harness's own README claims it is "run in CI";
that claim is aspirational — nothing runs it automatically today.
"""
import json
import pathlib
import sys

from jsonschema import Draft202012Validator

HERE = pathlib.Path(__file__).resolve().parent

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{(' - ' + detail) if detail and not condition else ''}")
    if not condition:
        failures.append(name)


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def validates(validator: Draft202012Validator, instance: object) -> bool:
    return next(iter(validator.iter_errors(instance)), None) is None


def main() -> int:
    capability_schema = load(HERE / "capability.schema.json")
    signal_schema = load(HERE / "signal.schema.json")
    Draft202012Validator.check_schema(capability_schema)
    Draft202012Validator.check_schema(signal_schema)
    cap = Draft202012Validator(capability_schema)
    sig = Draft202012Validator(signal_schema)

    print("Capability fixtures:")
    current_state = load(HERE / "fixtures" / "capability" / "current_state.json")
    check("current_state validates", validates(cap, current_state))
    check(
        "current_state declares NO produced signals",
        current_state["produces_signals"] == [],
        "it reads the signal columns but nothing writes them, so it is not a producer",
    )

    print("Signal fixtures:")
    signals = {}
    for name in ("velocity_7day", "stock_age_days", "unit_cost_trend_30day"):
        instance = load(HERE / "fixtures" / "signal" / f"{name}.json")
        signals[name] = instance
        check(f"{name} validates", validates(sig, instance))
        check(f"{name} declares no producers", instance["producers"] == [])

    print("The undetermined state is representable AND used (the point of the contract):")
    # If these ever go green by being "fixed" to a concrete unit, someone has invented
    # a fact. DIS's column comments are the source of truth and both say TBD.
    check(
        "velocity_7day unit is undetermined (DIS says unit-of-time is TBD)",
        signals["velocity_7day"]["unit"] == "undetermined",
    )
    check(
        "velocity_7day direction IS known (more velocity is better)",
        signals["velocity_7day"]["direction"] == "higher_is_better",
    )
    check(
        "unit_cost_trend_30day has BOTH undetermined (DIS says the semantic is TBD)",
        signals["unit_cost_trend_30day"]["unit"] == "undetermined"
        and signals["unit_cost_trend_30day"]["direction"] == "undetermined",
    )
    check(
        "stock_age_days is FULLY specified (its comment leaves nothing TBD)",
        signals["stock_age_days"]["unit"] == "days"
        and signals["stock_age_days"]["direction"] == "lower_is_better",
    )
    check(
        "a fully-specified signal needs no semantic_note",
        "semantic_note" not in signals["stock_age_days"],
    )

    print("Negative cases (must be rejected):")

    def clone(base: dict) -> dict:
        return json.loads(json.dumps(base))

    bad_version = clone(current_state)
    bad_version["version"] = "v1"
    check("capability: non-SemVer version is rejected", not validates(cap, bad_version))

    extra_field = clone(current_state)
    extra_field["cost_class"] = "cheap"
    check(
        "capability: an unknown field is rejected (schema is closed)",
        not validates(cap, extra_field),
    )

    bad_tenancy = clone(current_state)
    bad_tenancy["tenancy"] = "all_tenants"
    check(
        "capability: an invented tenancy value is rejected",
        not validates(cap, bad_tenancy),
        "tenancy must be declared, never acquired by naming something new",
    )

    no_signals_key = clone(current_state)
    del no_signals_key["produces_signals"]
    check(
        "capability: OMITTING produces_signals is rejected",
        not validates(cap, no_signals_key),
        "an empty list is a claim; a missing key is a silence, and they must not be the same",
    )

    empty_grain = clone(current_state)
    empty_grain["grain"] = []
    check("capability: an empty grain is rejected", not validates(cap, empty_grain))

    dup_grain = clone(current_state)
    dup_grain["grain"] = ["tenant_id", "tenant_id"]
    check("capability: a duplicated grain column is rejected", not validates(cap, dup_grain))

    # THE LOAD-BEARING NEGATIVE. If undetermined could be declared without a reason,
    # the honest state becomes a dumping ground for unfinished declarations and the
    # contract stops meaning anything.
    undetermined_unexplained = clone(signals["velocity_7day"])
    del undetermined_unexplained["semantic_note"]
    check(
        "signal: undetermined WITHOUT a semantic_note is rejected",
        not validates(sig, undetermined_unexplained),
        "undetermined must carry its reason or it is indistinguishable from unfinished",
    )

    explained_determinate = clone(signals["stock_age_days"])
    explained_determinate["semantic_note"] = "a note on a fully specified signal is allowed"
    check(
        "signal: a semantic_note on a DETERMINATE signal is still allowed",
        validates(sig, explained_determinate),
        "the rule is one-way: undetermined requires a note, a note does not imply undetermined",
    )

    invented_unit = clone(signals["stock_age_days"])
    invented_unit["unit"] = "widgets_per_fortnight"
    check("signal: an invented unit is rejected", not validates(sig, invented_unit))

    print("Scope guard (the other five contracts are NOT in this slice):")
    # D3: model, analysis, action, tool and content are later and would be guesses.
    # If a file for one appears, this fails rather than letting it arrive unnoticed.
    # NB: Path("capability.schema.json").stem is "capability.schema", not
    # "capability" — a double extension. Strip the suffix explicitly rather than
    # relying on .stem, which silently matched nothing and made this guard pass
    # vacuously on the first run.
    expected = {"capability", "signal"}
    unexpected = sorted(
        p.name
        for p in HERE.glob("*.schema.json")
        if p.name.removesuffix(".schema.json") not in expected
    )
    check(
        "only capability + signal schemas exist",
        unexpected == [],
        f"unexpected schema files: {unexpected}",
    )
    for absent in ("model", "analysis", "action", "tool", "content"):
        check(
            f"no {absent} schema has appeared",
            not (HERE / f"{absent}.schema.json").exists(),
        )

    print("Closed-schema guard:")
    check(
        "capability schema is closed (additionalProperties false)",
        capability_schema.get("additionalProperties") is False,
    )
    check(
        "signal schema is closed (additionalProperties false)",
        signal_schema.get("additionalProperties") is False,
    )

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("OK: all conformance checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
