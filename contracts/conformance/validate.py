#!/usr/bin/env python3
"""Conformance harness for the C6 pack contract.

Validates the example packs against the manifest and payload JSON Schemas,
verifies per-section content digests, runs negative cases (a non-SemVer version
and a missing signature block must be rejected), and asserts the scope guard
(date tokens and quarantine rules are absent from the payload schema).

This is a conformance check, not an implementation: no registry service, no
loader, no signing. Pure validation. Run: python3 conformance/validate.py
"""
import hashlib
import json
import pathlib
import sys

from jsonschema import Draft202012Validator

ROOT = pathlib.Path(__file__).resolve().parent.parent
PACK = ROOT / "pack"

failures: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {name}{(' - ' + detail) if detail and not condition else ''}")
    if not condition:
        failures.append(name)


def load(path: pathlib.Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def canonical_sha256(body: object) -> str:
    canon = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canon.encode("utf-8")).hexdigest()


def validates(validator: Draft202012Validator, instance: object) -> bool:
    return next(iter(validator.iter_errors(instance)), None) is None


def main() -> int:
    manifest_schema = load(PACK / "pack-manifest.schema.json")
    payload_schema = load(PACK / "pack-payload.schema.json")
    Draft202012Validator.check_schema(manifest_schema)
    Draft202012Validator.check_schema(payload_schema)
    manifest_validator = Draft202012Validator(manifest_schema)
    payload_validator = Draft202012Validator(payload_schema)

    print("Conformance fixtures:")
    for pack in ("retail", "insurance-cac"):
        manifest = load(PACK / "fixtures" / pack / "manifest.json")
        payload = load(PACK / "fixtures" / pack / "payload.json")
        check(f"{pack}: manifest validates", validates(manifest_validator, manifest))
        check(f"{pack}: payload validates", validates(payload_validator, payload))

        # Per-section content digests match the payload sections.
        recomputed = {section: canonical_sha256(body) for section, body in payload.items()}
        check(
            f"{pack}: content_digests cover exactly the payload sections",
            set(manifest["content_digests"]) == set(recomputed),
        )
        digests_ok = all(
            manifest["content_digests"].get(section) == digest
            for section, digest in recomputed.items()
        )
        check(f"{pack}: every section digest matches", digests_ok)

    print("Negative cases (must be rejected):")
    base = load(PACK / "fixtures" / "insurance-cac" / "manifest.json")

    bad_version = json.loads(json.dumps(base))
    bad_version["version"] = "v1"
    check("non-SemVer version is rejected", not validates(manifest_validator, bad_version))

    missing_sig = json.loads(json.dumps(base))
    del missing_sig["signature"]
    check("missing signature block is rejected", not validates(manifest_validator, missing_sig))

    print("Op-vocabulary negative cases (regression guard for the loose-array bug):")
    # The payload schema once typed normalize/derive op args as unconstrained
    # arrays, so a mapping with an unknown op or a missing required arg passed
    # conformance yet failed DIS SourceMapping.model_validate. The closed op
    # vocabulary (sourced from DIS libs/dis-mapping) must now reject all of these.
    retail_payload = load(PACK / "fixtures" / "retail" / "payload.json")

    def with_rules(mutate) -> dict:
        clone = json.loads(json.dumps(retail_payload))
        mutate(clone["mapping_rules"][0]["rules"])
        return clone

    unknown_op = with_rules(
        lambda r: r["normalize"].__setitem__(
            "source_sale_timestamp", [{"op": "parse_timestamp", "args": {"format": "%Y"}}]
        )
    )
    check("normalize with an unknown op is rejected", not validates(payload_validator, unknown_op))

    missing_arg = with_rules(
        lambda r: r["normalize"].__setitem__(
            "source_sale_timestamp", [{"op": "parse_datetime", "args": {"timezone": "UTC"}}]
        )
    )
    check(
        "parse_datetime missing required 'format' is rejected",
        not validates(payload_validator, missing_arg),
    )

    unknown_arg = with_rules(
        lambda r: r["normalize"].__setitem__(
            "source_sale_timestamp", [{"op": "parse_datetime", "args": {"date_token": "DD-MM-YYYY"}}]
        )
    )
    check(
        "the original date_token divergence is rejected",
        not validates(payload_validator, unknown_arg),
    )

    bad_generator_arg = with_rules(
        lambda r: r["derive"].__setitem__(
            "event_date", [{"op": "date_from_datetime", "args": {"source": "source_sale_timestamp"}}]
        )
    )
    check(
        "derive date_from_datetime with 'source' (not 'source_column') is rejected",
        not validates(payload_validator, bad_generator_arg),
    )

    unknown_generator = with_rules(
        lambda r: r["derive"].__setitem__(
            "event_date", [{"op": "now", "args": {}}]
        )
    )
    check(
        "derive list starting with an unknown generator is rejected",
        not validates(payload_validator, unknown_generator),
    )

    unknown_cast = with_rules(
        lambda r: r["cast"].__setitem__("quantity", {"type": "int64"})
    )
    check("cast to an unknown type is rejected", not validates(payload_validator, unknown_cast))

    decimal_missing_ps = with_rules(
        lambda r: r["cast"].__setitem__("unit_retail_price", {"type": "decimal"})
    )
    check(
        "cast to decimal without precision/scale is rejected",
        not validates(payload_validator, decimal_missing_ps),
    )

    print("Derive-composition (structural type-flow) negative case:")
    # STRUCTURAL rule mirrored from DIS SourceMapping._validate_derive_list:
    # normalize ops are str -> str, date_from_datetime yields a date, so no
    # normalize op may follow a date_from_datetime generator. Encoded in the
    # derive_list $def (date_from_datetime => exactly one element).
    date_then_normalize = with_rules(
        lambda r: r["derive"].__setitem__(
            "event_date",
            [
                {"op": "date_from_datetime", "args": {"source_column": "source_sale_timestamp"}},
                {"op": "normalize_case", "args": {"mode": "upper"}},
            ],
        )
    )
    check(
        "a normalize op after date_from_datetime is rejected",
        not validates(payload_validator, date_then_normalize),
    )

    print("Scope guard (engine-global, not in the pack payload):")
    payload_props = payload_schema.get("properties", {})
    check("date_tokens absent from payload schema", "date_tokens" not in payload_props)
    check("quarantine_rules absent from payload schema", "quarantine_rules" not in payload_props)
    check(
        "payload schema is closed (additionalProperties false)",
        payload_schema.get("additionalProperties") is False,
    )

    print()
    if failures:
        print(f"FAILED: {len(failures)} check(s): {', '.join(failures)}")
        return 1
    print("OK: all conformance checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
