// Phase 5e.1: client-side CSV export for templates. A template captures
// the source_column shape customers ship; this builds an empty CSV
// matching that shape so customers can download, fill, and upload back.
//
// Client-side Blob only — no backend, no MSW. Data already lives in
// `useTemplate(id)`'s React Query cache; the export is a pure
// transformation. When backend ships /dis/templates/{id}/csv later,
// swap `downloadTemplateCsv` for a fetch + save without touching the
// pure builders below.

import type { Template, TemplateColumnMapping } from "@/types/dis";

// Realistic placeholders by transformation type. Goal: the example row
// shows the expected format concretely without looking like a real row
// the customer might keep. The first cell is always the EXAMPLE banner
// (see buildTemplateCsv) so transformation-specific placeholders only
// apply from column 2 onward.
const PLACEHOLDER_BY_TRANSFORMATION: Record<string, string> = {
  TRIM: "abc123",
  UPPERCASE: "STORE001",
  LOWERCASE: "user@example.com",
  ISO_DATE: "2026-05-12",
  NUMERIC: "42.50",
};

const DEFAULT_PLACEHOLDER = "value";
const EXAMPLE_FIRST_CELL = "EXAMPLE — delete this row";

// Lowercase, strip combining diacritics, replace non-alphanumeric runs
// with a single hyphen, trim leading/trailing hyphens. "Żabka POS Sales
// Daily" → "zabka-pos-sales-daily".
export function slugify(input: string): string {
  return input
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
}

// RFC 4180: fields containing comma, double-quote, CR, or LF must be
// enclosed in double-quotes; literal quotes inside are doubled.
function csvEscape(value: string): string {
  if (/[",\r\n]/.test(value)) {
    return `"${value.replace(/"/g, '""')}"`;
  }
  return value;
}

function placeholderFor(mapping: TemplateColumnMapping, index: number): string {
  if (index === 0) return EXAMPLE_FIRST_CELL;
  if (mapping.transformation === null) return DEFAULT_PLACEHOLDER;
  return PLACEHOLDER_BY_TRANSFORMATION[mapping.transformation] ?? DEFAULT_PLACEHOLDER;
}

export function buildTemplateCsv(template: Template): string {
  const headerRow = template.column_mappings
    .map((m) => csvEscape(m.source_column))
    .join(",");
  const exampleRow = template.column_mappings
    .map((m, i) => csvEscape(placeholderFor(m, i)))
    .join(",");
  // CRLF per RFC 4180 — Excel + most parsers handle either, but CRLF
  // maximizes cross-tool compat.
  return `${headerRow}\r\n${exampleRow}\r\n`;
}

export function getTemplateCsvFilename(template: Template): string {
  return `${slugify(template.name)}.csv`;
}

// Browser-only. Caller must invoke from a user-gesture handler (click,
// keypress) for the download to be permitted by the browser.
export function downloadTemplateCsv(template: Template): void {
  const csv = buildTemplateCsv(template);
  const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = getTemplateCsvFilename(template);
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
