# Conformance

`validate.py` is the conformance harness for the contracts in this repo. It is a
validation check, not an implementation (no service, no loader, no signing).

It currently covers the C6 pack contract: validates the `retail` and
`insurance-cac` example packs against the manifest and payload schemas, verifies
the per-section content digests, runs the negative cases (a non-SemVer version
and a missing signature block must be rejected), and asserts the scope guard
(date tokens and quarantine rules are absent from the payload schema).

## Run

```
python3 conformance/validate.py
```

Needs Python 3 and `jsonschema`. Exits non-zero if any check fails; the
`contracts` job in `.github/workflows/ci.yml` runs it on every pull request.
