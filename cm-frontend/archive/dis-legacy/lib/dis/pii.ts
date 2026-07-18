// PII redaction utility for DIS sample-row displays. Used by
// SampleRowsTable and ColumnMappingRow's inline samples.
//
// Two redaction signals (defense in depth, per Phase 5c.1c A6):
//   1. Heuristic regex match on the value itself
//   2. Canonical-schema field tagged pii: true
// Either signal triggers redaction; both clean keeps the value.
//
// Phase 5c.1c A11 amendment notes: phone heuristic is intentionally
// permissive — false-positive cost (over-redact a tracking code or
// numeric ID) is preferred over false-negative cost (leak). Real
// backend may use stricter detection or rely entirely on schema tags
// when canonical-schema coverage is high.

import type { CanonicalSchemaDomain } from "@/types/dis";

const EMAIL_RE = /[\w.+-]+@[\w-]+(\.[\w-]+)+/g;
const PHONE_RE = /(\+?\d[\d\s().-]{7,}\d)/g;
const CARD_RE = /\b\d{4}[\s-]?\d{4}[\s-]?\d{4}[\s-]?\d{4}\b/g;
const SSN_RE = /\b\d{3}-\d{2}-\d{4}\b/g;

export function heuristicMatchesPii(value: string): boolean {
  if (!value) return false;
  EMAIL_RE.lastIndex = 0;
  PHONE_RE.lastIndex = 0;
  CARD_RE.lastIndex = 0;
  SSN_RE.lastIndex = 0;
  return (
    EMAIL_RE.test(value) ||
    PHONE_RE.test(value) ||
    CARD_RE.test(value) ||
    SSN_RE.test(value)
  );
}

export function canonicalFieldIsPii(
  canonicalFieldId: string | null | undefined,
  schema: CanonicalSchemaDomain[] | undefined,
): boolean {
  if (!canonicalFieldId || !schema) return false;
  for (const d of schema) {
    const f = d.fields.find((f) => f.id === canonicalFieldId);
    if (f) return f.pii;
  }
  return false;
}

export function shouldRedact(
  value: string,
  canonicalFieldId: string | null | undefined,
  schema: CanonicalSchemaDomain[] | undefined,
): boolean {
  return heuristicMatchesPii(value) || canonicalFieldIsPii(canonicalFieldId, schema);
}

// Mask format per Phase 5c.1c A10:
//   Email — partial: first char of local-part + first char of domain + TLD
//   Phone / card / SSN — full mask
//   Other (matched by canonical-schema tag but not regex) — full mask
//
// Example: "pat.k@example.com" -> "p**@e******.com"
export function redact(value: string): string {
  if (!value) return value;
  EMAIL_RE.lastIndex = 0;
  if (EMAIL_RE.test(value)) {
    return value.replace(EMAIL_RE, redactEmail);
  }
  PHONE_RE.lastIndex = 0;
  if (PHONE_RE.test(value)) return "••••••••";
  CARD_RE.lastIndex = 0;
  if (CARD_RE.test(value)) return "•••• •••• •••• ••••";
  SSN_RE.lastIndex = 0;
  if (SSN_RE.test(value)) return "•••-••-••••";
  // Schema-tagged but not regex-matched (e.g. a customer_id column
  // tagged pii on a custom canonical field). Full mask preserves
  // length signal without leaking content.
  return "•".repeat(Math.max(4, Math.min(value.length, 12)));
}

function redactEmail(match: string): string {
  const [local, domain] = match.split("@");
  if (!local || !domain) return "•".repeat(8);
  const dotIdx = domain.lastIndexOf(".");
  const tld = dotIdx >= 0 ? domain.slice(dotIdx) : "";
  const domainBody = dotIdx >= 0 ? domain.slice(0, dotIdx) : domain;
  const localMasked = local.charAt(0) + "**";
  const domainMasked = domainBody.charAt(0) + "*".repeat(Math.max(1, domainBody.length - 1));
  return `${localMasked}@${domainMasked}${tld}`;
}
