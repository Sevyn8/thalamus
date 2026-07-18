import type { CanonicalSchemaField } from "@/types/dis";

// Phase 5c.8b1: classifies a canonical-field edit as additive,
// breaking, or neutral. Pure function — reusable in 5c.8b2's
// BumpVersionModal which aggregates classifications across pending
// edits per domain.
//
// v1 client-side classifier is a UX prediction layer, not a contract
// enforcement: it warns Anjali before save. Real backend may
// implement a stronger classifier server-side later (querying actual
// referenced_by counts in real-time + downstream parser compat
// checks). Until then, this is the demo signal.
//
// Rules:
//   BREAKING — type change (any), required tightening (false → true),
//              nullable removal (true → false), unique tightening
//              (false → true), constraint addition, pii removal
//              (true → false — surfaces previously-redacted data).
//   ADDITIVE — synonym addition, example_values addition, constraint
//              relaxation (removing a constraint), required loosening
//              (true → false), nullable addition (false → true), pii
//              addition (false → true).
//   NEUTRAL  — display_name / description / business_owner edits,
//              changes that don't affect schema shape.
//
// When multiple changes are made in one edit, the result is BREAKING
// if any change is breaking; ADDITIVE if any change is additive AND
// none are breaking; NEUTRAL otherwise.

export type ClassificationKind = "additive" | "breaking" | "neutral";

export type ClassificationResult = {
  kind: ClassificationKind;
  reasons: string[];
};

export function classifyChange(
  before: CanonicalSchemaField,
  after: Partial<CanonicalSchemaField>,
): ClassificationResult {
  const reasons: string[] = [];
  let kind: ClassificationKind = "neutral";

  function escalate(next: ClassificationKind): void {
    if (kind === "breaking") return;
    if (next === "breaking") kind = "breaking";
    else if (next === "additive") kind = "additive";
  }

  // Type change: always breaking.
  if (after.type !== undefined && after.type !== before.type) {
    reasons.push(
      `Type changed from ${before.type} to ${after.type} — breaks existing data parsing.`,
    );
    escalate("breaking");
  }

  // Required tightening (false → true): breaking.
  if (
    after.required !== undefined &&
    after.required !== (before.required ?? false)
  ) {
    if (after.required) {
      reasons.push(
        "Required tightening (was optional) — existing rows without this field will fail validation.",
      );
      escalate("breaking");
    } else {
      reasons.push("Required loosening (now optional) — additive widening.");
      escalate("additive");
    }
  }

  // Nullable removal (true → false): breaking.
  if (
    after.nullable !== undefined &&
    after.nullable !== (before.nullable ?? true)
  ) {
    if (!after.nullable) {
      reasons.push(
        "Nullable removed — existing null values will fail validation.",
      );
      escalate("breaking");
    } else {
      reasons.push("Nullable added — additive widening.");
      escalate("additive");
    }
  }

  // Unique tightening (false → true): breaking.
  if (after.unique !== undefined && after.unique !== (before.unique ?? false)) {
    if (after.unique) {
      reasons.push(
        "Uniqueness added — existing duplicate values will fail validation.",
      );
      escalate("breaking");
    } else {
      reasons.push("Uniqueness removed — additive widening.");
      escalate("additive");
    }
  }

  // Constraint addition: breaking. Removal: additive.
  if (after.constraints !== undefined) {
    const beforeSet = new Set(before.constraints ?? []);
    const afterSet = new Set(after.constraints);
    const added = [...afterSet].filter((c) => !beforeSet.has(c));
    const removed = [...beforeSet].filter((c) => !afterSet.has(c));
    if (added.length > 0) {
      reasons.push(
        `Constraint added (${added.join(", ")}) — existing rows may fail validation.`,
      );
      escalate("breaking");
    }
    if (removed.length > 0) {
      reasons.push(
        `Constraint removed (${removed.join(", ")}) — additive widening.`,
      );
      escalate("additive");
    }
  }

  // PII flag flip: removal is breaking (surfaces previously-redacted
  // data), addition is additive.
  if (after.pii !== undefined && after.pii !== before.pii) {
    if (!after.pii) {
      reasons.push(
        "PII flag removed — previously-redacted values will now surface in payloads.",
      );
      escalate("breaking");
    } else {
      reasons.push("PII flag added — values will be redacted at apply.");
      escalate("additive");
    }
  }

  // Synonyms addition: additive. Removal: neutral (synonyms only
  // affect LLM-mapping suggestion ranking, not data shape).
  if (after.synonyms !== undefined) {
    const beforeSet = new Set(before.synonyms);
    const afterSet = new Set(after.synonyms);
    const added = [...afterSet].filter((s) => !beforeSet.has(s));
    if (added.length > 0) {
      reasons.push(
        `Synonyms added (${added.join(", ")}) — better LLM-mapping coverage.`,
      );
      escalate("additive");
    }
  }

  // Example values addition: additive. (Example values are
  // documentation; they don't affect schema shape.)
  if (after.example_values !== undefined) {
    const beforeSet = new Set(before.example_values ?? []);
    const afterSet = new Set(after.example_values);
    const added = [...afterSet].filter((v) => !beforeSet.has(v));
    if (added.length > 0) {
      reasons.push(`Example values added (${added.length} new).`);
      escalate("additive");
    }
  }

  // Display name / description / business_owner edits: neutral
  // (no schema-shape impact).
  if (kind === "neutral" && reasons.length === 0) {
    reasons.push("Documentation-only edit (no schema-shape impact).");
  }

  return { kind, reasons };
}
