#!/usr/bin/env node
// P1-SEC-001. Fail the production build if development auth material reached dist/.
//
// WHY A BYTE SCAN AND NOT A CODE REVIEW. The module-graph boundary lives in vite.config.ts
// (the '@devAuthSeam' alias) and it is the actual fix. This script is the measurement: an
// alias that stops being applied, a new static import of src/auth/dev from somewhere in the
// production tree, or a future bundler that inlines a chunk differently would all leave the
// boundary looking correct in source while the artifact regressed. The deployed v18 bundle
// carried the stub secret, both persona emails and the seeded tenant/store UUIDs; the only
// check that would have caught that is one that reads what shipped.
//
// WHY THESE MARKERS. Every one is a VALUE, not an identifier. Minification renames
// `STUB_SECRET` and `PERSONAS` freely but cannot rewrite the string literals they hold, so a
// value-based scan survives the optimizer. Identifier-based checks would pass on a minified
// bundle that still contains the key.
//
// This runs as part of `pnpm build`, which is what the Dockerfile and the dis-ui-ver2 CI job
// both invoke, so it is on the deployment path rather than being a command somebody remembers.

import { readdirSync, readFileSync, statSync } from 'node:fs'
import { join, relative } from 'node:path'
import { fileURLToPath } from 'node:url'

const ROOT = fileURLToPath(new URL('..', import.meta.url))
const DIST = join(ROOT, 'dist')

// label -> literal that must not appear in any emitted asset.
const FORBIDDEN = [
  ['stub HS256 signing key', 'dis-ui-dev-stub-secret-not-for-production'],
  ['stub token issuer', 'https://customer-master.local'],
  ['dev login route', '/dev/login'],
  ['dev persona email (tenant)', 'a.kowalski@zabka.pl'],
  ['dev persona email (platform)', 'anjali@ithina.ai'],
  ['dev persona subject', 'u_acmeuser0001'],
  ['seeded dev tenant UUID', '019e5e3c-b5d6-7eed-93f9-3778a7a7a160'],
  ['seeded dev store UUID', '019e5e3c-b633-7344-93c7-83fb205285ea'],
]

// Binary assets (fonts, images) cannot meaningfully contain these and would only add noise.
const SKIP_EXTENSIONS = new Set(['.woff', '.woff2', '.ttf', '.otf', '.eot', '.png', '.jpg', '.jpeg', '.gif', '.ico', '.webp', '.avif'])

function walk(dir) {
  const out = []
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry)
    if (statSync(full).isDirectory()) {
      out.push(...walk(full))
    } else {
      out.push(full)
    }
  }
  return out
}

let files
try {
  files = walk(DIST)
} catch (error) {
  console.error(`[assert-no-dev-auth] cannot read ${DIST}: ${error.message}`)
  console.error('[assert-no-dev-auth] the build must run before this check.')
  process.exit(1)
}

// VACUITY GUARD. Every assertion below reads files and counts matches, so an empty or
// unreadable dist/ would report a clean bundle having scanned nothing. Absence of assets is a
// failure here, not a pass.
const scannable = files.filter((f) => !SKIP_EXTENSIONS.has(f.slice(f.lastIndexOf('.')).toLowerCase()))
const scripts = scannable.filter((f) => f.endsWith('.js') || f.endsWith('.mjs'))
if (scripts.length === 0) {
  console.error('[assert-no-dev-auth] no .js/.mjs assets found in dist/. Refusing to report a')
  console.error('[assert-no-dev-auth] clean artifact from an empty scan.')
  process.exit(1)
}

const findings = []
for (const file of scannable) {
  const text = readFileSync(file, 'utf8')
  for (const [label, needle] of FORBIDDEN) {
    if (text.includes(needle)) {
      findings.push({ file: relative(ROOT, file), label, needle })
    }
  }
}

if (findings.length > 0) {
  console.error('')
  console.error('[assert-no-dev-auth] DEVELOPMENT AUTH MATERIAL IS PRESENT IN THE PRODUCTION ARTIFACT.')
  console.error('')
  for (const { file, label, needle } of findings) {
    console.error(`  ${file}`)
    console.error(`    ${label}: ${JSON.stringify(needle)}`)
  }
  console.error('')
  console.error('  Anything in dist/ is served to browsers and is therefore public. The stub')
  console.error('  signing key is accepted by dis-ui-server whenever it runs in STUB mode, and the')
  console.error('  claims it carries drive RLS, so a shipped key is a forgeable tenant-scoped login.')
  console.error('')
  console.error('  This is a module-graph problem, not a runtime one. Find the static import that')
  console.error('  reaches src/auth/dev/** from the production tree - a runtime guard such as')
  console.error('  `if (import.meta.env.PROD) throw` will NOT remove these bytes. Dev-only code')
  console.error('  belongs behind @devAuthSeam (src/auth/seam/), which vite.config.ts resolves to')
  console.error('  devAuthSeam.prod.tsx for deployable builds.')
  console.error('')
  process.exit(1)
}

console.log(
  `[assert-no-dev-auth] ${scannable.length} emitted assets scanned (${scripts.length} script), ` +
    `${FORBIDDEN.length} markers, none present.`,
)
