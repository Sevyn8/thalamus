#!/usr/bin/env node
// Fail the build if the channel credential surface could expose, retain or re-fill a tenant's
// provider credential.
//
// WHAT THIS PROTECTS. Sevyn8 never sees a tenant's sending credential. That is not a policy
// written down somewhere and honoured by care: cm-backend's IAM role (cmChannelVaultWriter)
// omits secretmanager.versions.access, so the service CANNOT read a stored credential back, and
// its read model has no field one could travel in. This script is the frontend half of the same
// promise, and it exists because the frontend half is the easy one to undo. A reveal toggle is
// a five-line pull request that looks like a usability improvement.
//
// WHY A SCRIPT AND NOT A TEST. cm-frontend has NO test runner. `next build` plus the assertion
// scripts in this directory are the entire gate, so anything asserted has to be asserted here.
// Same discipline as assert-launcher-tiles.mjs and assert-dynamic-routes.mjs: assert the
// ARTIFACT, not the intent, because a type is defeated by `as any` and a convention is defeated
// by anyone who did not read it.
//
// THE VACUITY GUARD IS NOT OPTIONAL AND IS NOT CEREMONY. Every check below reads a file and
// counts matches. A rename, a move or a refactor that stops the regex matching would make every
// assertion pass against nothing, and a passing build would then certify a property nobody
// checked. So: an unreadable file exits 1, and a scan that finds ZERO credential inputs exits 1.
// Absence is a failure here, not a pass. This project has already paid for "0 == 0 proves
// nothing" more than once.
//
// WHAT THIS CANNOT SEE, stated rather than implied:
//   1. What the browser does. autoComplete is a request to a password manager, not a control
//      over one. A manager may still offer to store the value.
//   2. Anything at runtime. If cm-backend ever grew a route that returned a credential, no build
//      check here would notice; the guarantee upstream is the missing IAM permission, and
//      cm-backend/tests/unit/test_deployment_posture.py is what asserts that.
//   3. A credential typed into some other form entirely. This reads the channel surface only.

import { existsSync, readFileSync, readdirSync } from "node:fs";

const FORM = "components/channels/ChannelCredentialForm.tsx";
const GENERATED_TYPES = "types/openapi-generated.ts";
const CHANNELS_DIR = "components/channels";
const MY_ITHINA_DIR = "app/my-ithina";

let failures = 0;

function fail(message) {
  console.error(`assert-channel-credential-safety: ${message}`);
  failures += 1;
}

function read(path) {
  try {
    return readFileSync(path, "utf8");
  } catch (cause) {
    console.error(
      `assert-channel-credential-safety: cannot read ${path} (${String(cause)}). A path that ` +
        `does not resolve covers nothing, and every check below would pass against an empty ` +
        `string. If the file moved, update this script in the same commit.`,
    );
    process.exit(1);
  }
}

const formSource = read(FORM);
const typesSource = read(GENERATED_TYPES);

// ---------------------------------------------------------------------------
// 1. THE VACUITY GUARD. Find the credential value inputs, and refuse a zero parse.
// ---------------------------------------------------------------------------
// Matched on the accessible name rather than on a class or an ordinal, because the accessible
// name is the thing that cannot change without the field meaning something different.
//
// SCANNED WITH BRACE DEPTH RATHER THAN A REGEX, and the first attempt here is worth recording:
// `<Input\b[^>]*aria-label="..."[^>]*\/>` cannot cross the `>` in an `onChange={(e) => ...}`
// arrow, so it matched ZERO inputs against a form that has three. The vacuity guard below caught
// it on the first run. Had this script been written without one, it would have reported success
// while examining nothing, which is the precise failure it exists to prevent.
function extractTags(source, tagName) {
  const tags = [];
  const opener = `<${tagName}`;
  let index = source.indexOf(opener);
  while (index !== -1) {
    let depth = 0;
    let cursor = index + opener.length;
    while (cursor < source.length) {
      const char = source[cursor];
      if (char === "{") depth += 1;
      else if (char === "}") depth -= 1;
      else if (depth === 0 && char === "/" && source[cursor + 1] === ">") {
        tags.push(source.slice(index, cursor + 2));
        break;
      } else if (depth === 0 && char === ">") {
        // A non-self-closing tag. Not a shape this form uses, and taking the
        // opening tag alone is the right conservative read of its attributes.
        tags.push(source.slice(index, cursor + 1));
        break;
      }
      cursor += 1;
    }
    index = source.indexOf(opener, cursor);
  }
  return tags;
}

const credentialInputs = extractTags(formSource, "Input").filter((tag) =>
  tag.includes('aria-label="Credential value"'),
);

if (credentialInputs.length === 0) {
  fail(
    `found ZERO credential value inputs in ${FORM}. Either the form no longer has one, or it ` +
      `was renamed and this script is now asserting nothing. Both are build failures: a check ` +
      `that matches nothing reports success for a property it never examined.`,
  );
}

// ---------------------------------------------------------------------------
// 2. EVERY credential value input is type="password", AS A LITERAL.
// ---------------------------------------------------------------------------
// The literal is the point. `type={revealed ? "text" : "password"}` is exactly the change this
// forbids, and it would satisfy a check that merely looked for the word "password".
for (const input of credentialInputs) {
  if (!/\btype="password"/.test(input)) {
    fail(
      `a credential value input in ${FORM} is not type="password" as a literal. A reveal toggle ` +
        `puts another company's provider credential on screen; there is no supported reason to ` +
        `show it, because nothing can read it back to compare against.`,
    );
  }
  if (/\btype=\{/.test(input)) {
    fail(
      `a credential value input in ${FORM} computes its type. Even when the expression is ` +
        `currently correct, it is one edit from a reveal control and this check cannot evaluate it.`,
    );
  }
}

// ---------------------------------------------------------------------------
// 3. NOTHING CAN PRE-FILL IT, asserted at the CONTRACT rather than at the markup.
// ---------------------------------------------------------------------------
// Scanning JSX for a value binding would be the weaker check: it can only see the shapes it
// thought of. If the RESPONSE TYPE cannot carry a credential, no pre-fill can exist anywhere,
// including in code this script never reads.
const READ_MODELS = ["ChannelConnectionRead", "PlatformChannelConnectionRead"];
const FORBIDDEN_FIELD = /^\s*(credential|password|secret_value|secret|value|credentials)\??:/;

for (const model of READ_MODELS) {
  const start = typesSource.indexOf(`${model}: {`);
  if (start === -1) {
    fail(
      `${model} is not in ${GENERATED_TYPES}. Either the backend contract changed or the types ` +
        `were not regenerated; either way this script cannot see what it claims to check.`,
    );
    continue;
  }
  // The generated file is uniformly indented, so the model body ends at the first line that
  // closes it at the same depth. Bounded scan, no brace counting needed.
  const body = typesSource.slice(start, typesSource.indexOf("\n        };", start));
  if (body.length === 0) {
    fail(`could not read the body of ${model} in ${GENERATED_TYPES}`);
    continue;
  }
  for (const line of body.split("\n")) {
    if (FORBIDDEN_FIELD.test(line)) {
      fail(
        `${model} has a field that could carry a credential: "${line.trim()}". The read path is ` +
          `supposed to return secret_ref (the secret's NAME) and never a value. If cm-backend ` +
          `really added this, that is the thing to stop, not this check.`,
      );
    }
  }
  if (!/secret_ref\??:/.test(body)) {
    fail(
      `${model} no longer carries secret_ref. That field is what lets an operator discuss a ` +
        `specific stored credential without anyone reading one; losing it silently removes the ` +
        `only handle the surface has.`,
    );
  }
}

// ---------------------------------------------------------------------------
// 4. The credential inputs ask a password manager not to store the value.
// ---------------------------------------------------------------------------
// A request, not a control (see WHAT THIS CANNOT SEE). Asserted anyway because its absence is
// silent and its presence costs nothing.
for (const input of credentialInputs) {
  if (!/autoComplete="(new-password|off)"/.test(input)) {
    fail(
      `a credential value input in ${FORM} has no autoComplete="new-password" or "off", so a ` +
        `browser password manager may offer to store another company's provider credential.`,
    );
  }
}

// ---------------------------------------------------------------------------
// 5. Nothing in the channel components logs.
// ---------------------------------------------------------------------------
// A console.log added while debugging a form is how a credential reaches a browser console, and
// on a server component it is how one reaches Cloud Logging for the bucket's retention.
for (const file of readdirSync(CHANNELS_DIR)) {
  if (!file.endsWith(".tsx") && !file.endsWith(".ts")) continue;
  const source = read(`${CHANNELS_DIR}/${file}`);
  const stripped = source
    .replace(/\/\*[\s\S]*?\*\//g, "")
    .replace(/(^|[^:])\/\/.*$/gm, "$1");
  if (/\bconsole\.\w+\(/.test(stripped)) {
    fail(
      `${CHANNELS_DIR}/${file} calls console.*. These components handle a tenant's credential in ` +
        `component state; a debug log is how one leaves the browser.`,
    );
  }
}

// ---------------------------------------------------------------------------
// 6. The two structural decisions, asserted as artifacts rather than as prose.
// ---------------------------------------------------------------------------
// NO [tenantId] SEGMENT under the tenant surface. The tenant is in the token, and RLS scopes
// every row. A path segment would create a token-versus-path mismatch that then needs
// quarantining; adding the trap and guarding it is worse than not adding it.
const dynamicSegments = readdirSync(MY_ITHINA_DIR, { withFileTypes: true })
  .filter((e) => e.isDirectory() && e.name.startsWith("["))
  .map((e) => e.name);

if (dynamicSegments.length > 0) {
  fail(
    `${MY_ITHINA_DIR} has dynamic segment(s) ${dynamicSegments.join(", ")}. The tenant comes from ` +
      `the token on this surface. A tenant id in the path is a second source of truth for the ` +
      `same fact, and the two disagreeing is a case that has to be quarantined rather than read.`,
  );
}

// NO SECOND TENANT-FACING PREFIX. app/ has exactly one, and my-ithina carrying an old brand name
// is a rename decision on its own, not a reason to start a second tree beside it.
if (existsSync("app/my-sevyn8")) {
  fail(
    `app/my-sevyn8 exists. There is one tenant-facing top-level group and it is app/my-ithina. ` +
      `Two prefixes means every future tenant surface has to pick one, and half of them will ` +
      `pick differently. Renaming my-ithina is its own decision, taken once, everywhere.`,
  );
}

// ---------------------------------------------------------------------------

if (failures > 0) {
  console.error(
    `assert-channel-credential-safety: ${failures} failure(s). The build is stopped.`,
  );
  process.exit(1);
}

console.log(
  `assert-channel-credential-safety: ${credentialInputs.length} credential input(s) checked, ` +
    `${READ_MODELS.length} read model(s) verified to carry no credential field, path decisions intact`,
);
