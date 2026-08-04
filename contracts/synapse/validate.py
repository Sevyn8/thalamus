#!/usr/bin/env python3
"""Conformance harness for the Synapse capability, signal and analysis contracts.

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
    analysis_schema = load(HERE / "analysis.schema.json")
    Draft202012Validator.check_schema(capability_schema)
    Draft202012Validator.check_schema(signal_schema)
    Draft202012Validator.check_schema(analysis_schema)
    cap = Draft202012Validator(capability_schema)
    sig = Draft202012Validator(signal_schema)
    ana = Draft202012Validator(analysis_schema)

    print("Capability fixtures:")
    current_state = load(HERE / "fixtures" / "capability" / "current_state.json")
    check("current_state validates", validates(cap, current_state))
    check(
        "current_state declares NO produced signals",
        current_state["produces_signals"] == [],
        "it reads the signal columns but nothing writes them, so it is not a producer",
    )
    check(
        "current_state declares NO gates",
        current_state["gates"] == [],
        "the hot table either has a row or does not; no quantity of history changes that",
    )

    daily_series = load(HERE / "fixtures" / "capability" / "daily_series.json")
    check("daily_series validates", validates(cap, daily_series))
    check(
        "daily_series is the FIRST as_of_date capability",
        daily_series["freshness"] == "as_of_date" and current_state["freshness"] == "last_write",
        "the enum value existed unused until a series needed it; conflating the two is the "
        "mistake it was added to prevent",
    )
    check(
        "daily_series declares the min_history_days gate KIND and no value",
        daily_series["gates"] == ["min_history_days"],
        "the threshold moved to the demand side; a value here would be the slice-1 shape",
    )

    last_sale_at = load(HERE / "fixtures" / "capability" / "last_sale_at.json")
    check("last_sale_at validates", validates(cap, last_sale_at))
    check(
        "last_sale_at shares current_state's grain EXACTLY",
        last_sale_at["grain"] == current_state["grain"],
        "the universe and the presences must join; dead_stock is the difference between them",
    )
    check(
        "last_sale_at declares NO gates",
        last_sale_at["gates"] == [],
        "'when did this last sell' is answerable from one observation",
    )
    check(
        "last_sale_at is last_write, not as_of_date",
        last_sale_at["freshness"] == "last_write",
        "its VALUE is a date; no date PARAMETER is meaningful, which is what the enum means",
    )
    check(
        "daily_series grain includes event_date",
        "event_date" in daily_series["grain"],
        "an as_of_date capability whose grain has no date is a reading, not a series",
    )
    check(
        "daily_series declares no produced signals",
        daily_series["produces_signals"] == [],
    )

    # THE MONEY CHECK, and it is a content rule rather than a schema rule because no schema
    # can express "do not add a field whose meaning is unresolved". tax_treatment is per-row
    # INCLUSIVE/EXCLUSIVE denormalized from the store, so summing quantity * unit_sale_price
    # across a tenant adds tax-inclusive to tax-exclusive amounts with nothing declaring a
    # normalization. If a money field appears here, that decision was made silently.
    money_words = ("amount", "price", "revenue", "value", "cost", "total")
    money_fields = sorted(f for f in daily_series["returns"] if any(w in f for w in money_words))
    check(
        "daily_series returns QUANTITY only, no money field",
        money_fields == [],
        f"money needs a tax_treatment normalization decision first; found {money_fields}",
    )

    capability_ids = [current_state["id"], daily_series["id"], last_sale_at["id"]]
    check("the capability ids are distinct", len(set(capability_ids)) == len(capability_ids))
    fixture_count = len(list((HERE / "fixtures" / "capability").glob("*.json")))
    check(
        "exactly THREE capability fixtures exist",
        fixture_count == 3,
        f"found {fixture_count}; lead_time_distribution must NOT have one — its absence is "
        "the point, and the reason lives in synapse/registry.py's _DECLINED",
    )

    print("Analysis fixtures (the DEMAND side, new in slice 2):")
    dead_stock = load(HERE / "fixtures" / "analysis" / "dead_stock.json")
    check("dead_stock validates", validates(ana, dead_stock))
    required_ids = [r["capability_id"] for r in dead_stock["requires"]]
    check(
        "dead_stock composes TWO capabilities",
        sorted(required_ids) == ["current_state", "last_sale_at"],
        f"found {sorted(required_ids)}",
    )
    check(
        "dead_stock's grain is contained in both required capabilities' grains",
        set(dead_stock["grain"]) <= set(current_state["grain"])
        and set(dead_stock["grain"]) <= set(last_sale_at["grain"]),
        "a coarser capability cannot be joined at a finer grain without inventing rows",
    )
    for requirement in dead_stock["requires"]:
        fixture_for = {"current_state": current_state, "last_sale_at": last_sale_at}[
            requirement["capability_id"]
        ]
        check(
            f"every field dead_stock reads from {requirement['capability_id']} is in its returns",
            set(requirement["fields"]) <= set(fixture_for["returns"]),
            f"missing {sorted(set(requirement['fields']) - set(fixture_for['returns']))}",
        )
        check(
            f"dead_stock binds exactly the gates {requirement['capability_id']} declares",
            [g["kind"] for g in requirement["gates"]] == fixture_for["gates"],
            "an unbound declared gate never runs; a bound undeclared gate has no probe",
        )

    # THE FITTED-THRESHOLD RULE, as a content check. No schema can express "this constant is
    # honest about being one" beyond requiring the field; this asserts the field says something.
    (stale_after,) = dead_stock["thresholds"]
    check(
        "stale_after_days admits it is NOT fitted",
        stale_after["fitted"] is False,
        "if this ever flips to true, the p90-gap capability must actually exist",
    )
    check(
        "stale_after_days names what it stands in for, specifically",
        "p90" in stale_after["stands_in_for"] and len(stale_after["stands_in_for"]) > 120,
        "a one-word placeholder is not a derivation; it must say what the fitted version is",
    )
    check(
        "dead_stock needs NO history gate anywhere",
        all(r["gates"] == [] for r in dead_stock["requires"]),
        "absence is the signal, so it works on sparse data — the reason it is the first one",
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

    # THE SLICE-1 PRECONDITION NEGATIVES ARE GONE, and their absence is the finding rather
    # than a gap. They asserted things about a precondition carrying a VALUE here — an invented
    # kind, days=0, a negative, a stringly-typed number, an extra field inside the object, a
    # duplicate. None of those are expressible against `gates` because `gates` holds no values:
    # the schema now admits only an enum of kind names, so "days=0 is rejected" has no shape to
    # test. Six negative cases collapsed into three (a gate carrying a value at all, an
    # invented kind, an omitted key), and the day-range negatives MOVED to the analysis
    # contract, where the days actually live.
    empty_grain = clone(current_state)
    empty_grain["grain"] = []
    check("capability: an empty grain is rejected", not validates(cap, empty_grain))

    gate_with_a_value = clone(daily_series)
    gate_with_a_value["gates"] = [{"kind": "min_history_days", "days": 60}]
    check(
        "capability: a gate carrying a VALUE is rejected",
        not validates(cap, gate_with_a_value),
        "this is the slice-1 shape; the threshold belongs to the caller now",
    )

    invented_gate_kind = clone(daily_series)
    invented_gate_kind["gates"] = ["min_freshness_hours"]
    check(
        "capability: an invented gate kind is rejected",
        not validates(cap, invented_gate_kind),
        "a kind may be declared only where a probe exists, so a new one is a schema edit",
    )

    no_gates_key = clone(current_state)
    del no_gates_key["gates"]
    check(
        "capability: OMITTING gates is rejected",
        not validates(cap, no_gates_key),
        "an empty list is a claim, a missing key is a silence",
    )

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

    no_requires = clone(dead_stock)
    no_requires["requires"] = []
    check(
        "analysis: requiring NO capability is rejected",
        not validates(ana, no_requires),
        "an analysis with no inputs has nothing to analyse",
    )

    empty_fields = clone(dead_stock)
    empty_fields["requires"][0]["fields"] = []
    check(
        "analysis: a requirement naming NO fields is rejected",
        not validates(ana, empty_fields),
        "an analysis that reads nothing from a capability does not require it",
    )

    no_policy = clone(dead_stock)
    no_policy["requires"][0]["gates"] = [{"kind": "min_history_days", "days": 90}]
    check(
        "analysis: a gate with a threshold but NO policy is rejected",
        not validates(ana, no_policy),
        "THE LOAD-BEARING NEGATIVE: a threshold with no policy is slice 1's unowned default "
        "coming back — the number without what 'enough' means across a population",
    )

    invented_policy = clone(dead_stock)
    invented_policy["requires"][0]["gates"] = [
        {"kind": "min_history_days", "days": 90, "policy": "min_series"}
    ]
    check(
        "analysis: an invented policy is rejected",
        not validates(ana, invented_policy),
        "min-over-series is all_series with a worse name and must not be spellable",
    )

    zero_day_gate = clone(dead_stock)
    zero_day_gate["requires"][0]["gates"] = [
        {"kind": "min_history_days", "days": 0, "policy": "any_series"}
    ]
    check("analysis: a zero-day gate is rejected", not validates(ana, zero_day_gate))

    unfitted_unexplained = clone(dead_stock)
    del unfitted_unexplained["thresholds"][0]["stands_in_for"]
    check(
        "analysis: an UNFITTED threshold with no stands_in_for is rejected",
        not validates(ana, unfitted_unexplained),
        "a constant with no stated derivation is indistinguishable from a guess — the same "
        "one-way rule as a signal's undetermined/semantic_note pair",
    )

    fitted_but_substituting = clone(dead_stock)
    fitted_but_substituting["thresholds"][0]["fitted"] = True
    check(
        "analysis: a FITTED threshold that still stands in for something is rejected",
        not validates(ana, fitted_but_substituting),
        "a fitted number substitutes for nothing; leaving the note would be a stale claim",
    )

    fitted_clean = clone(dead_stock)
    fitted_clean["thresholds"] = [{"name": "stale_after_days", "days": 90, "fitted": True}]
    check(
        "analysis: a FITTED threshold with no stands_in_for is ACCEPTED",
        validates(ana, fitted_clean),
        "the rule is one-way, exactly like semantic_note: unfitted requires a reason, and a "
        "reason is not what makes something unfitted",
    )

    analysis_extra = clone(dead_stock)
    analysis_extra["schedule"] = "0 3 * * *"
    check(
        "analysis: an unknown field is rejected (schema is closed)",
        not validates(ana, analysis_extra),
        "a schedule and an output destination are the two most tempting additions and nothing "
        "consumes an analysis's output yet",
    )

    print("Scope guard (the other four contracts are NOT in this slice):")
    # model, action, tool and content are later and would be guesses. If a file for one
    # appears, this fails rather than letting it arrive unnoticed.
    #
    # `analysis` MOVED FROM THIS LIST TO THE ONE ABOVE in slice 2. Slice 1 asserted "no
    # analysis schema has appeared"; that guard did its job by making the arrival deliberate
    # rather than incidental, and flipping it is the visible edit it existed to force.
    # NB: Path("capability.schema.json").stem is "capability.schema", not
    # "capability" — a double extension. Strip the suffix explicitly rather than
    # relying on .stem, which silently matched nothing and made this guard pass
    # vacuously on the first run.
    expected = {"capability", "signal", "analysis"}
    unexpected = sorted(
        p.name
        for p in HERE.glob("*.schema.json")
        if p.name.removesuffix(".schema.json") not in expected
    )
    check(
        "only capability + signal + analysis schemas exist",
        unexpected == [],
        f"unexpected schema files: {unexpected}",
    )
    for absent in ("model", "action", "tool", "content"):
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
    check(
        "analysis schema is closed (additionalProperties false)",
        analysis_schema.get("additionalProperties") is False,
    )

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("OK: all conformance checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
