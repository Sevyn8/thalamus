#!/usr/bin/env node
// Fail the build if any Synapse console route was PRERENDERED.
//
// WHY THIS EXISTS. Every Synapse data page reads SYNAPSE_BFF_URL and the caller's
// session at request time. Prerendering executes them during `next build`, where
// neither exists — the fetch throws, the page catches it, and "The Synapse service
// is not reachable" is serialised into static HTML that the container then serves
// for ever. That shipped once: the running revision had the variable set, the BFF's
// logs were empty, and the console showed a well-written error naming the exact
// variable that was in fact correctly configured.
//
// `export const dynamic = "force-dynamic"` prevents it, and the session-read-first
// ordering in lib/synapse/server-client.ts prevents it again. Both are things an
// edit can undo silently. THIS ASSERTS THE ARTIFACT INSTEAD OF THE INTENT — the
// same discipline as the BFF Dockerfile resolving $ASGI_TARGET with uvicorn's own
// importer rather than trusting that two hand-written strings agree.
//
// HOW IT DETECTS A PRERENDERED ROUTE: Next.js writes .next/server/app/<route>.html
// for pages it rendered at build time, and writes no such file for dynamic ones.
// That file IS the defect — it is the thing that would be served — so its presence
// is the most direct evidence available, more direct than parsing the ○ / ƒ markers
// out of stdout, which are a human-readable rendering of the same fact.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

// Routes that MUST be server-rendered on demand. Atlas is deliberately absent: it
// reads nothing, has no API by design (an endpoint returning empty is
// indistinguishable from a broken one), and is correct to prerender.
const MUST_BE_DYNAMIC = [
  "superadmin/synapse",
  "superadmin/synapse/runs",
  // The fleet alerts inbox. Reads /alerts and /alerts/state-counts per request
  // and takes its filters from the query string, so a prerender would freeze one
  // reader's filtered view into static HTML for everyone.
  "superadmin/synapse/alerts",
  "superadmin/synapse/capabilities",
  "superadmin/synapse/analyses",
  // THE TWO TENANT-SCOPED ROUTES WERE UNGUARDED UNTIL 5c, which was a gap rather than
  // a decision: both read the BFF and the session per request exactly like the four
  // above, so both carry the same prerender hazard and neither was being checked. The
  // dynamic-segment routes are listed by their MANIFEST path ([tenantId], not a
  // concrete id) because that is the key the build emits.
  "superadmin/synapse/tenants/[tenantId]",
  "superadmin/synapse/tenants/[tenantId]/alerts/[eventId]",
  // AXON's delivery ledger. Not a Synapse route and listed here anyway:
  // this file guards the console's server-rendered pages, not one module's. It
  // reads the BFF and the session per request exactly like the six above, so a
  // prerender would bake one moment's ledger into static HTML and the page would
  // stop changing while deliveries kept being written.
  "superadmin/axon/deliveries",
];

const APP_DIR = join(process.cwd(), ".next", "server", "app");

if (!existsSync(APP_DIR)) {
  console.error(
    `assert-dynamic-routes: ${APP_DIR} does not exist — run this after \`next build\`, ` +
      `not instead of it. Exiting non-zero rather than passing vacuously.`,
  );
  process.exit(1);
}

// A VACUITY GUARD. If the Synapse pages are not in the build at all, every check
// below passes trivially — the "0 == 0 proves nothing" failure this project has
// paid for elsewhere. So absence is a failure, not a pass.
//
// app-path-routes-manifest.json is the authoritative list of routes the build
// produced, static and dynamic alike. On-disk artefacts are not: a prerendered
// route leaves <route>.html while a dynamic one leaves nothing at this path, so
// looking for a file would report every correctly-dynamic route as missing.
const manifestPath = join(process.cwd(), ".next", "app-path-routes-manifest.json");
if (!existsSync(manifestPath)) {
  console.error(`assert-dynamic-routes: ${manifestPath} not found; run after \`next build\`.`);
  process.exit(1);
}
const routes = new Set(Object.values(JSON.parse(readFileSync(manifestPath, "utf8"))));
const missing = MUST_BE_DYNAMIC.filter((r) => !routes.has(`/${r}`));
if (missing.length > 0) {
  console.error(
    `assert-dynamic-routes: these routes are not in the build at all: ${missing.join(", ")}. ` +
      `Either they were renamed — update MUST_BE_DYNAMIC — or the build did not produce them. ` +
      `Passing here would prove nothing.`,
  );
  process.exit(1);
}

const prerendered = MUST_BE_DYNAMIC.filter((route) => existsSync(join(APP_DIR, `${route}.html`)));

if (prerendered.length > 0) {
  console.error("");
  console.error("  BUILD REFUSED: Synapse routes were PRERENDERED at build time.");
  console.error("");
  for (const route of prerendered) {
    console.error(`    /${route}  ->  .next/server/app/${route}.html exists`);
  }
  console.error("");
  console.error("  These pages read SYNAPSE_BFF_URL and the caller's session per request.");
  console.error("  Prerendered, they run during `next build` where neither exists, and the");
  console.error("  resulting error notice is baked into HTML the container serves for ever —");
  console.error("  while the deployed revision has the variable set correctly.");
  console.error("");
  console.error('  Fix: `export const dynamic = "force-dynamic"` in the page, and keep the');
  console.error("  session read first in lib/synapse/server-client.ts so the route is dynamic");
  console.error("  BY USE and not only by declaration.");
  console.error("");
  process.exit(1);
}

console.log(
  `assert-dynamic-routes: ${MUST_BE_DYNAMIC.length} Synapse routes are server-rendered on demand`,
);
