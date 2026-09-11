"""dis-pii — PII detection and a fail-loud gate.

Two responsibilities only, as pure functions over a caller-supplied source mapping
(no DB access, no crypto, no network):

- :func:`detect_pii_columns` — which columns a mapping flags as PII (field-name and
  pattern based).
- :func:`assert_pii_handled` — the fail-loud gate: if any PII column is detected and
  no backend is configured to handle it, raise *before* any persistence path so PII
  cannot land silently. In v1.0 no real backend exists, so the gate raises on every
  detected PII column.

Detection is **heuristic** (field-name / pattern matching), so the gate fires only on
what the matcher catches; a PII column the matcher does not recognise passes silently.
This limitation, and the absence of an explicit per-column PII flag in the mapping
contract, are both current constraints — do not read detection as exhaustive.

No tokenization, key-vault, or crypto implementation exists in this package.
"""

from __future__ import annotations

from dis_pii.detectors import detect_pii_columns
from dis_pii.gate import PiiBackend, assert_pii_handled

__all__ = ["PiiBackend", "assert_pii_handled", "detect_pii_columns"]
