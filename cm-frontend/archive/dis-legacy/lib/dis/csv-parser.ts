// Phase 5c.1b hotfix: minimal CSV parser used to extract header + first
// N data rows on the client. Stand-in for backend CSV parsing — Phase
// 5d migrates parsing server-side once multipart uploads land, at which
// point this client-side step becomes redundant and can be removed.
//
// Scope: header row + first N data rows. Handles RFC 4180 basics —
// quoted fields, escaped quotes ("" inside ""), CR/LF line endings.
// Does NOT handle: streaming, custom delimiters, BOM, multi-line
// values that span more rows than `maxDataRows + 1`. Real backend
// supersedes for any of those cases.

export type ParsedCsvSlice = {
  headers: string[];
  sample_rows: string[][];
};

export async function parseCsvSlice(
  file: File,
  maxDataRows = 5,
): Promise<ParsedCsvSlice | null> {
  if (!file.name.toLowerCase().endsWith(".csv")) return null;

  // 256 KB is plenty for a header row + 5 sample rows even on wide
  // schemas; avoids slurping the whole file into memory for the
  // 10MB+ ingest cases. Real backend reads streamingly anyway.
  const slice = await file.slice(0, 256 * 1024).text();
  const rows = parseRfc4180(slice, maxDataRows + 1);
  if (rows.length === 0) return null;

  const headers = rows[0]!.map((h) => h.trim());
  const sample_rows = rows.slice(1, 1 + maxDataRows);
  return { headers, sample_rows };
}

function parseRfc4180(input: string, maxRows: number): string[][] {
  const rows: string[][] = [];
  let row: string[] = [];
  let field = "";
  let inQuotes = false;

  for (let i = 0; i < input.length; i++) {
    const ch = input[i]!;
    if (inQuotes) {
      if (ch === '"') {
        if (input[i + 1] === '"') {
          field += '"';
          i++;
        } else {
          inQuotes = false;
        }
      } else {
        field += ch;
      }
      continue;
    }
    if (ch === '"') {
      inQuotes = true;
    } else if (ch === ",") {
      row.push(field);
      field = "";
    } else if (ch === "\n" || ch === "\r") {
      row.push(field);
      rows.push(row);
      field = "";
      row = [];
      if (ch === "\r" && input[i + 1] === "\n") i++;
      if (rows.length >= maxRows) return rows;
    } else {
      field += ch;
    }
  }
  if (field.length > 0 || row.length > 0) {
    row.push(field);
    rows.push(row);
  }
  return rows;
}
