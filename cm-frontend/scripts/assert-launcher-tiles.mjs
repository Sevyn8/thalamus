#!/usr/bin/env node
// Fail the build if the launcher's tile registry and the ModuleCode union disagree.
//
// THE DEFECT THIS EXISTS FOR. lib/launcher/visibility.ts resolves a tenant's tiles by looking
// each enabled module code up in LAUNCHER_TILES. Before Axon slice 4 a code with no tile
// produced an empty array: the module vanished from the launcher and nothing anywhere reported
// it. A tenant granted a module would see one fewer workspace than they were entitled to, with
// no error, no log and no way to tell it apart from not being granted it at all.
//
// THIS IS ONE OF THREE GUARDS AND THE WEAKEST OF THEM ON ITS OWN. Stated plainly so nobody
// treats it as sufficient:
//
//   1. THE TYPE. tiles.ts declares PRODUCT_TILES as Record<ModuleCode, ...>, so a missing or
//      unknown key is a tsc error and `next build` typechecks. That is stronger than this
//      script against a reformat, because a regex can stop matching and a type cannot.
//   2. THIS SCRIPT. It asserts the ARTIFACT rather than the intent, which is the discipline
//      assert-dynamic-routes.mjs was written under. A type is defeated by `as any`, by a stray
//      `@ts-expect-error`, or by anyone setting typescript.ignoreBuildErrors, and none of those
//      would be visible in a diff that looked like a formatting change.
//   3. THE RUNTIME BRANCH in visibility.ts. It is the only one that can catch the case that
//      actually happens in production: MODULE ACCESS IS DATA. A module enabled for a tenant
//      after this image shipped never passes through any build check at all, and neither the
//      type nor this script can see it. A build assertion alone would be exactly the false
//      comfort that defaulted environment variables gave three times this week.
//
// WHY IT PARSES TEXT. tiles.ts imports lucide-react, so a plain node script cannot import it,
// and there is no test runner in this package to do it properly. Text parsing is what the two
// existing scripts do and it is why the vacuity guard below is not optional.
//
// WHAT THIS CANNOT SEE, stated rather than implied:
//   1. A module code the SERVER can return that ModuleCode has never contained. Both sides read
//      from this repository; the wire does not. That is the runtime branch's job.
//   2. Whether a tile's href actually resolves. A tile can be present, typed, asserted here and
//      still point at a 404.

import { readFileSync } from "node:fs";

const API_TYPES = "types/api.ts";
const TILES = "lib/launcher/tiles.ts";

function read(path) {
  try {
    return readFileSync(path, "utf8");
  } catch (cause) {
    console.error(
      `assert-launcher-tiles: cannot read ${path} (${String(cause)}). A path that does not ` +
        `resolve covers nothing, and every comparison below would pass against an empty string.`,
    );
    process.exit(1);
  }
}

// ---------------------------------------------------------------------------
// Parse: the ModuleCode union, and the keys of PRODUCT_TILES.
// ---------------------------------------------------------------------------

const apiSource = read(API_TYPES);
const unionMatch = apiSource.match(/export type ModuleCode\s*=([\s\S]*?);/);
if (!unionMatch) {
  console.error(
    `assert-launcher-tiles: could not find "export type ModuleCode = ... ;" in ${API_TYPES}. ` +
      `The union has moved or been renamed. Passing here would prove nothing.`,
  );
  process.exit(1);
}
const moduleCodes = new Set([...unionMatch[1].matchAll(/"([A-Z][A-Z0-9_]*)"/g)].map((m) => m[1]));

const tilesSource = read(TILES);
const recordMatch = tilesSource.match(
  /const PRODUCT_TILES:\s*Record<ModuleCode,[^>]*>\s*=\s*\{([\s\S]*?)\n\};/,
);
if (!recordMatch) {
  console.error(
    `assert-launcher-tiles: could not find the PRODUCT_TILES Record literal in ${TILES}. ` +
      `Either it was renamed, or it is no longer typed Record<ModuleCode, ...>, which is the ` +
      `compile-time half of this guard. Passing here would prove nothing.`,
  );
  process.exit(1);
}
// Top-level keys only: SCREAMING_SNAKE identifier, colon, opening brace.
const tiled = new Set([...recordMatch[1].matchAll(/^\s{2}([A-Z][A-Z0-9_]*):\s*\{/gm)].map((m) => m[1]));

// ---------------------------------------------------------------------------
// THE VACUITY GUARD, PER SIDE rather than on a total.
//
// assert-no-em-dash.mjs learned this the hard way: it used to check only a total, which meant a
// large root could carry a small one and a misspelled path was invisible. The same shape applies
// to a two-sided comparison. If either side parses to nothing, the difference between the sets
// is empty and this script reports success having compared nothing at all. Each side is checked
// on its own, with its own message.
// ---------------------------------------------------------------------------

if (moduleCodes.size === 0) {
  console.error(
    `assert-launcher-tiles: parsed ZERO module codes out of ${API_TYPES}. The union's shape ` +
      `changed and the regex no longer matches its members. This script cannot compare an ` +
      `empty set against anything.`,
  );
  process.exit(1);
}
if (tiled.size === 0) {
  console.error(
    `assert-launcher-tiles: parsed ZERO tiles out of ${TILES}. The registry's shape changed ` +
      `and the key regex no longer matches. Every module would read as "covered" by an empty ` +
      `set, which is the exact silent pass this guard exists to prevent.`,
  );
  process.exit(1);
}

// ---------------------------------------------------------------------------
// Compare, BOTH DIRECTIONS, and report per file.
// ---------------------------------------------------------------------------

const missingTile = [...moduleCodes].filter((code) => !tiled.has(code)).sort();
const unknownCode = [...tiled].filter((code) => !moduleCodes.has(code)).sort();

if (missingTile.length > 0 || unknownCode.length > 0) {
  console.error("");
  console.error("  BUILD REFUSED: the launcher registry and the ModuleCode union disagree.");
  console.error("");
  if (missingTile.length > 0) {
    console.error(`    ${TILES}: no tile for ${missingTile.join(", ")}`);
    console.error(
      "      A tenant granted one of these would see a tile saying the console cannot render",
    );
    console.error(
      "      it. That runtime branch is a safety net, not the fix: add the tile here.",
    );
  }
  if (unknownCode.length > 0) {
    console.error(`    ${API_TYPES}: no ModuleCode member for ${unknownCode.join(", ")}`);
    console.error(
      "      This tile can never be shown, because no tenant can be granted a module the",
    );
    console.error("      union does not contain. Either add the member or remove the tile.");
  }
  console.error("");
  process.exit(1);
}

console.log(
  `assert-launcher-tiles: ${tiled.size} launcher tiles cover all ${moduleCodes.size} module codes`,
);
