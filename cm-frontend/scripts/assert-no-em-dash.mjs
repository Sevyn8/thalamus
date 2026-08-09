#!/usr/bin/env node
// Fail the build if an em-dash reaches a user from a TypeScript literal in the Synapse console.
//
// THE OTHER HALF LIVES IN THE BFF. This file walks frontend literals;
// synapse/services/synapse-ui-server/tests/test_no_em_dash_in_served_copy.py walks the copy the
// BFF serves and the console renders. Neither is sufficient alone, and the reason is a real
// miss: a frontend-only scan during B2b-1 reported zero em-dashes remaining, which was true and
// read as "the console is clean". The longest em-dash-bearing strings on the whole console were
// arriving from the BFF at that moment, in Threshold.stands_in_for. The scan was not wrong, it
// was blind to a category and nothing said so.
//
// WIRED INTO `pnpm build` rather than left as a command to remember. There is no CI in this
// repository, so a check nobody runs is worth nothing; this repo has already paid for a
// conformance harness documented as CI-run that nothing ran.
//
// COMMENTS ARE NOT OUTPUT, so they are stripped before matching. The Synapse frontend carries
// roughly seventy em-dashes in comments and docstrings and they are none of this rule's
// business: the rule governs what a user reads.
//
// WHAT THIS CANNOT SEE, stated rather than implied:
//   1. Anything the BFF serves. That is the Python half's job.
//   2. Customer data. A product named with an em-dash renders one; not our copy.
//   3. Strings built at runtime from values, e.g. `${a} — ${b}` survives only if the literal
//      part carries the character, which it would. Concatenation of two clean halves around a
//      variable that holds one does not.
//   4. Anything outside the Synapse directories below. The rest of cm-frontend is not covered
//      and is not claimed to be.

import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const EM_DASH = "—";

const ROOTS = [
  "components/synapse",
  "lib/synapse",
  "app/(authenticated)/superadmin/synapse",
];

function walk(dir) {
  const out = [];
  for (const entry of readdirSync(dir)) {
    const path = join(dir, entry);
    if (statSync(path).isDirectory()) out.push(...walk(path));
    else if (path.endsWith(".ts") || path.endsWith(".tsx")) out.push(path);
  }
  return out;
}

// Blank every comment span in place, so line numbers survive for the report.
function stripComments(source) {
  const lines = source.split("\n");
  // Block comments, including the {/* ... */} JSX form, possibly spanning lines.
  for (const match of source.matchAll(/\{?\/\*[\s\S]*?\*\/\}?/g)) {
    const before = source.slice(0, match.index);
    const start = before.split("\n").length - 1;
    const end = start + match[0].split("\n").length - 1;
    if (start === end) lines[start] = lines[start].replace(match[0], "");
    else for (let i = start; i <= end; i += 1) lines[i] = "";
  }
  return lines.map((line) => line.replace(/\/\/.*$/, ""));
}

const files = ROOTS.flatMap((root) => {
  try {
    return walk(root);
  } catch {
    return [];
  }
});

// A VACUITY GUARD. If the globs stop matching — a directory renamed, the script run from the
// wrong cwd — every check below passes trivially. Absence is a failure, not a pass.
if (files.length < 8) {
  console.error(
    `assert-no-em-dash: found only ${files.length} Synapse source files, which means the ` +
      `paths have moved or this ran from the wrong directory. Passing here would prove nothing.`,
  );
  process.exit(1);
}

const offenders = [];
for (const file of files) {
  stripComments(readFileSync(file, "utf8")).forEach((line, index) => {
    if (line.includes(EM_DASH)) offenders.push({ file, line: index + 1, text: line.trim() });
  });
}

if (offenders.length > 0) {
  console.error("");
  console.error("  BUILD REFUSED: em-dash in user-visible copy.");
  console.error("");
  for (const { file, line, text } of offenders) {
    console.error(`    ${file}:${line}  ${text.slice(0, 100)}`);
  }
  console.error("");
  console.error("  Use a comma, a semicolon, a colon or a full stop. Comments are exempt and");
  console.error("  are stripped before matching, so this is copy somebody will read on screen.");
  console.error("");
  process.exit(1);
}

console.log(`assert-no-em-dash: ${files.length} Synapse source files carry no rendered em-dash`);
