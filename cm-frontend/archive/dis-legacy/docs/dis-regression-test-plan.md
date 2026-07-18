# DIS frontend regression test plan

**Purpose.** Verify nothing built across Phase 5c.1 + 5c.2 (six chunks + nine hotfixes) has broken or drifted. Two passes: Pass 1 is the 15-minute "did anything obviously break" smoke; Pass 2 is the 45-minute "did any subtle behavior drift" regression. Run Pass 1 always; run Pass 2 before any push or deploy.

**Setup.**

1. `Ctrl+C` the dev server.
2. `rm -rf .next`
3. `pnpm dev`
4. Open Chrome with DevTools Console + Network tabs visible.
5. Have the demo CSV ready: `mocks/dis/test-fixtures/zabka-warsaw-sales-2026-04.csv` (14 columns including PII, generated for the upload demo path).
6. Personas available: Anjali (PLATFORM), Kowalski (TENANT, Żabka), and any other tenant persona configured.

**Recording results.** For each test case below, mark one of:
- PASS (works as expected)
- FAIL (genuine bug; capture screenshot + console state)
- PARTIAL (works but UX issue or warning; note details)
- N/A (precondition not met; explain)

Report back with pass/fail counts plus a list of FAILs ranked by severity (blocker / major / minor).

---

## Pass 1: Fast smoke (15 minutes)

Goal: catch the loud regressions. Each section is 2-3 quick checks.

### 1.1 Navigation chrome
1. Visit `/dis/sources` — page loads, sidebar visible, no console errors
2. Sidebar HELP section has 5 items (Onboarding, Docs, Status, Changelog, Settings) — Settings entry from 5c.1c hotfix is intact
3. Anjali sees 22 sidebar items total, Kowalski sees 18 (Anjali has admin section)
4. Switch persona via /dev/login — chrome updates, no stale state

### 1.2 Uploads happy path
1. As Kowalski, drop the demo CSV at `/dis/uploads` — file uploads, routes to detail
2. Detail page shows MappingReviewView body with column rows (NOT empty — verifies CSV synthesis hotfix)
3. Confidence chips visible across green/amber/red spectrum
4. SampleRowsTable renders with email/phone redacted

### 1.3 Sources happy path
1. `/dis/sources` lists all 10 fixtures (verify count includes Żabka Krakow store sync ONBOARDING)
2. Click any ACTIVE source — detail page renders with type-specific Config tab populated
3. Lifecycle action buttons (Pause/Run now/Rotate/Delete) visible per status
4. Anjali sees Force pause + Reassign ownership; Kowalski sees regular Pause, no Reassign

### 1.4 Wizard happy path
1. As Kowalski, click + New source — 5-step wizard renders
2. Pick Square card → OrgNode picker shows Żabka tree (alias hotfix verifies) → Config form has disabled "Connect with Square" button + identifier inputs
3. Test connection succeeds OR Skip path works
4. Save creates source with ACTIVE (or untested chip if skipped)

### 1.5 Settings + LLM gate
1. Visit `/dis/settings` directly — page renders
2. Toggle LLM-assist OFF — banner flips to "Currently disabled"
3. Open a PENDING_REVIEW upload — manual mapping path renders (no proposals)
4. Toggle back ON — re-open upload — LLM-on path renders

If all 5 sections pass, Pass 1 done. Report time elapsed and move on or escalate any FAILs.

---

## Pass 2: Deep regression (45 minutes)

Goal: catch subtle behavior drift, persona-specific edge cases, and cross-cutting concerns. Run after Pass 1 is clean.

### 2.1 Uploads surface (5c.1 trilogy + CSV synthesis hotfix)

| # | Test | Expected |
|---|------|----------|
| 2.1.1 | Drop demo CSV → mapping rows render | 14 column rows, varied confidence chips |
| 2.1.2 | PII columns (`customer_email`, `customer_phone`) get high-confidence chips | 0.78-0.92 confidence per heuristic |
| 2.1.3 | SampleRowsTable shows 5 rows, email rendered as `j**@e******.com`, phone as `••••••••` | Default redacted |
| 2.1.4 | As Anjali, "View raw" button visible per row in SampleRowsTable | Permission gate works |
| 2.1.5 | Click "View raw" → row reveals raw values, console shows `[dis-audit] pii_viewed { user_id, upload_id, revealed_columns, occurred_at }` | Audit fires |
| 2.1.6 | As Kowalski, "View raw" button NOT visible | Permission denied |
| 2.1.7 | Toggle LLM-assist OFF in /dis/settings → re-open same upload → manual mapping path renders | Gate works, "Manage in DIS settings" link in header |
| 2.1.8 | Click "Manage in DIS settings" link from manual-mapping header → routes to `/dis/settings` | Hotfix verified, no `/dis/dashboard/settings` 404 |
| 2.1.9 | Confirm mapping on PENDING_REVIEW upload → status flips to CONFIRMED, redirects to `/dis/uploads` | Mutation works |
| 2.1.10 | Re-open the now-CONFIRMED upload → mapping shown read-only, no edit affordances | Read-only mode |
| 2.1.11 | Open MID_INGEST fixture (`customer_loyalty_full_dump.csv`) → read-only mapping with PII redaction | Existing seeded behavior |
| 2.1.12 | Drop a non-CSV file → inline error, file rejected | Client-side validation |
| 2.1.13 | Drop malformed CSV (e.g., `.csv` with garbage content) → "No columns detected" empty state | Defensive fallback |
| 2.1.14 | Capability=false debug check: localStorage override capability key, reload `/dis/settings` as Kowalski → "Not available on your plan" | Capability gating |

### 2.2 Sources surface (5c.2 trilogy)

| # | Test | Expected |
|---|------|----------|
| 2.2.1 | `/dis/sources` lists 10 fixtures with type/status/health chips | All chips render |
| 2.2.2 | Filter by type SQUARE → narrows to Square sources | Filter logic |
| 2.2.3 | Filter by status PAUSED + health DEGRADED → intersection works | Multi-filter |
| 2.2.4 | Search input filters by name (try "Warsaw") | Text search |
| 2.2.5 | Click Square row → detail page with Merchant ID/Location ID/Environment in Config tab | Type-specific display |
| 2.2.6 | Click POS_API_GENERIC row → Endpoint URL/Auth type/Credentials masked (`••••••••`) | Generic display + masking |
| 2.2.7 | Click FTP row → Host/Port/Path/Username/Credentials masked | FTP display |
| 2.2.8 | Detail page Schedule card shows humanized + raw cron (e.g. "Every 15 minutes" + `*/15 * * * *`) | Cron humanizer hotfix |
| 2.2.9 | Edit form pre-fills cron with raw expression, NOT humanized | Edit form fix |
| 2.2.10 | Save edit form → routes back to detail, change persisted | PATCH works |
| 2.2.11 | ONBOARDING source (Buc-ee's Clover) — amber banner visible to ITS tenant only | Banner persona-gating |
| 2.2.12 | As Anjali on Buc-ee's Clover → status chip says Onboarding, but NO banner | Cross-tenant gating |
| 2.2.13 | Click banner "Continue setup" → routes to `/dis/sources/new?continue={id}` | Banner href flip |
| 2.2.14 | ContinueOnboardingFlow renders 2-step (Config → Test), NOT the 5-step wizard | Separate component |
| 2.2.15 | Save in continue flow → fires PATCH not POST, status flips ONBOARDING → ACTIVE | Update semantics |
| 2.2.16 | Skip-test in create wizard → saved source has amber "Untested at creation" chip next to Status | Untested chip |
| 2.2.17 | Skip-test path with successful Test (no skip) → no Untested chip | Conditional render |

### 2.3 Lifecycle actions (5c.2c1)

| # | Test | Expected |
|---|------|----------|
| 2.3.1 | ACTIVE source → Pause button visible, Resume hidden | Hide-by-status |
| 2.3.2 | Click Pause → status PAUSED, Pause hides, Resume appears | Mutation |
| 2.3.3 | Click Resume → flips ACTIVE | Reverse |
| 2.3.4 | Click Run now → "Last run" updates to "moments ago" or similar | Stub timestamp |
| 2.3.5 | Click Rotate credentials on FTP source → fires, credentials remain masked | Credential rotation stub |
| 2.3.6 | Click Delete → ConfirmDestructive opens with type-to-confirm | Single delete confirm |
| 2.3.7 | Type source name → Delete enables → confirm → source removed | Delete flow |
| 2.3.8 | Delete button visible on PAUSED, ERROR, ONBOARDING sources | Always-visible per A5 refinement |
| 2.3.9 | Disabled lifecycle buttons (e.g., on placeholder if any) show tooltip on hover | Tooltip wrapper-span |

### 2.4 Bulk actions (5c.2c2)

| # | Test | Expected |
|---|------|----------|
| 2.4.1 | Select 2 sources via checkbox → sticky bar appears with "2 selected" + Pause/Resume/Delete | Multi-select |
| 2.4.2 | Mixed-status (1 ACTIVE + 1 PAUSED) Pause click → toast "Pause: 1 of 2 succeeded" + skipped detail | Mixed-result handling |
| 2.4.3 | Filter narrows visible rows → selection count persists | Off-screen selection |
| 2.4.4 | Select-all checkbox in header → toggles all visible rows | Header checkbox |
| 2.4.5 | Bulk Delete → ConfirmDialog "Delete N sources?" (NO type-to-confirm) | Count-based confirm |
| 2.4.6 | Confirm bulk delete → all selected deleted, list refreshed, selection cleared | Bulk mutation |
| 2.4.7 | Clear-X on sticky bar → selection cleared, bar hides | Clear action |

### 2.5 Admin actions (5c.2c2 + alias hotfix)

| # | Test | Expected |
|---|------|----------|
| 2.5.1 | As Anjali on ACTIVE source → "Force pause" button (not "Pause") | Persona-aware label |
| 2.5.2 | Click Force pause → status flips PAUSED, console logs `[dis-audit] admin_force_pause` with all 7 fields | Audit payload |
| 2.5.3 | As Anjali → "Reassign ownership" button visible in governance row beneath lifecycle row | Separate row, hotfix |
| 2.5.4 | Reassign visible on ACTIVE, PAUSED, ERROR, ONBOARDING sources for Anjali | Status-independent |
| 2.5.5 | Click Reassign → modal opens, native select shows tenant-users (NOT empty) | Alias-lift hotfix |
| 2.5.6 | Pick different user → Save → owner_name updates | Reassign mutation |
| 2.5.7 | Console logs `[dis-audit] admin_reassign_ownership` with `previous_owner_user_id` AND `new_owner_user_id` | Audit fields |
| 2.5.8 | As Kowalski → no "Force pause" (regular Pause), no Reassign button | Platform-only gating |

### 2.6 Wizard create flow (5c.2b1 + 5c.2b2)

| # | Test | Expected |
|---|------|----------|
| 2.6.1 | As Kowalski, `/dis/sources/new` → Step 1 Type catalog with 9 cards | Type selector |
| 2.6.2 | Pick Square → Next → Step 2 OrgNode shows Żabka tree (alias resolves) | Picker works |
| 2.6.3 | Pick a node → Next → Step 3 Config shows NamedPosOAuthForm | Type-specific form |
| 2.6.4 | Disabled "Connect with Square" button visible as primary affordance + helper text | A2 amendment |
| 2.6.5 | Identifier inputs labeled "auto-populated post-OAuth" | Secondary visual |
| 2.6.6 | Pick CSV_SCHEDULED in Step 1 → Step 3 has NO Connect button (config-only) | Type differentiation |
| 2.6.7 | Step 4 Test → click Test → spinner 400-1200ms → success/failure (~80% rate) | Random success |
| 2.6.8 | Failure → Retry + Back-to-config buttons; cycles 4 error codes across retries | Error taxonomy |
| 2.6.9 | Step 4 → "Skip - untested at creation" button alongside Test (always visible) | Skip-test |
| 2.6.10 | Click Skip → amber panel "Untested - may fail on first run" → Continue enabled | Skip UX |
| 2.6.11 | Step 5 Schedule → name input + cron input + 3 preset buttons (Hourly/Daily/Weekly) | Schedule step |
| 2.6.12 | Click Daily preset → fills `0 6 * * *` | Preset works |
| 2.6.13 | Save → routes to detail page → ACTIVE status | Create succeeds |
| 2.6.14 | Cancel at any step → silent discard, routes to /dis/sources | Cancel UX |
| 2.6.15 | Back at any step → previous step retains draft data | Draft preservation |
| 2.6.16 | As Anjali → +New source disabled with tooltip on hover | Persona gating + tooltip |

### 2.7 Continue onboarding flow (5c.2c3 + Żabka fixture hotfix)

| # | Test | Expected |
|---|------|----------|
| 2.7.1 | As Kowalski, open Żabka Krakow store sync from list → ONBOARDING status chip | Fixture exists |
| 2.7.2 | Detail page → amber "Awaiting configuration. Continue setup →" banner visible | Banner for tenant-of-source |
| 2.7.3 | Click banner link → routes to `/dis/sources/new?continue={id}` | Href flip |
| 2.7.4 | ContinueOnboardingFlow renders, header "Complete setup for Żabka Krakow store sync" | Focused flow |
| 2.7.5 | Step 1 of 2: Config (Lightspeed form: account_id + environment) | 2-step indicator |
| 2.7.6 | Fill config → Next → Step 2 of 2: Test → either Test or Skip | Test step |
| 2.7.7 | Save button labeled "Complete setup" → click → fires PATCH (Network tab confirms) | PATCH not POST |
| 2.7.8 | Routes to detail → status now ACTIVE, banner gone | Status flip |
| 2.7.9 | If skipped → Untested chip visible next to Status | Untested propagation |
| 2.7.10 | As Anjali, manually visit `/dis/sources/new?continue={Żabka_id}` → redirects to detail | Cross-tenant guard |
| 2.7.11 | Visit `?continue={ACTIVE_id}` → redirects to detail with toast | Wrong-status guard |
| 2.7.12 | Visit `?continue={bogus_id}` → "Redirecting..." spinner → /dis/sources + toast "Source not found" | 404 redirect |

### 2.8 Cross-cutting concerns

| # | Test | Expected |
|---|------|----------|
| 2.8.1 | DevTools Console clean on `/dis/sources` (no nativeButton warnings) | Hotfix held |
| 2.8.2 | Console clean on `/dis/uploads`, `/dis/settings` | No warnings |
| 2.8.3 | Network tab on Reassign Save → POST `/api/v1/dis/audit-events` returns 204 | Audit pipeline |
| 2.8.4 | `/superadmin/org` regression as Anjali → Buc-ee's tree renders identically (alias-lift didn't break Ithina) | Cross-product safety |
| 2.8.5 | `/superadmin/users` regression as Anjali → users list works (Phase 4d) | Ithina baseline |
| 2.8.6 | Switch persona via /dev/login → chrome reflects new persona, no stale data | Persona switch |
| 2.8.7 | Hard refresh (Ctrl+Shift+R) on `/dis/sources/[id]` → page renders fresh, no hydration errors | SSR/CSR boundary |
| 2.8.8 | Direct URL navigation to `/dis/uploads/[id]` for a fixture → renders | Direct deep-link |

### 2.9 Persona matrix

For each surface, verify both personas:

| Surface | Anjali (PLATFORM) | Kowalski (TENANT) |
|---------|-------------------|-------------------|
| `/dis/sources` | All 10 sources visible | Same (MSW no-RLS) |
| +New source button | Disabled with tooltip | Enabled, navigates |
| Source detail lifecycle | Force pause + Reassign | Pause, no Reassign |
| Bulk actions | Force-pause across tenants | Tenant-scoped |
| `/dis/uploads` | All uploads visible | Same |
| PII redaction "View raw" | Visible | Hidden |
| `/dis/settings` | Loads, shows platform context (or fallback) | Loads, shows Żabka prefs |
| ONBOARDING banner | Hidden (cross-tenant) | Visible on Żabka sources |
| Continue flow | Redirects on direct URL | Loads happy path |

### 2.10 LOC and lint baseline check

| # | Test | Expected |
|---|------|----------|
| 2.10.1 | `pnpm tsc --noEmit` | Exit 0 |
| 2.10.2 | `pnpm lint` | 1 pre-existing error + 4 pre-existing warnings (Sidebar baseline); no new |
| 2.10.3 | `pnpm build` | 52 routes register cleanly |
| 2.10.4 | `git status -s` | Clean (no uncommitted changes) |
| 2.10.5 | `git log --oneline main..dis-frontend-local \| wc -l` | Matches expected commit count (currently 23 +1 with this regression confirms) |

---

## Reporting format

After running, report back in this shape:

```
Pass 1: X/Y passed (X/Y sections clean)
Pass 2: X/Y passed across N test cases

FAILs:
[BLOCKER] 2.X.Y: <description> + screenshot/console state
[MAJOR] 2.X.Y: <description>
[MINOR] 2.X.Y: <description>

PARTIALs:
2.X.Y: <description + UX issue noted>

Time elapsed: X minutes (Pass 1) + Y minutes (Pass 2)

Next action: proceed to 5c.3a / hotfix needed for {issues} / re-run after fix
```

---

## Notes for Claude Code

- **No fixture mutation during regression.** If a test creates/deletes/edits a source, restore by hard-refreshing the page (in-memory MSW state resets on the next dev-server restart anyway).
- **PII audit events are expected to fire** during PII test cases. They populate the console; that's the verification, not noise.
- **Random test-connection failures are expected** in 2.6.7-2.6.8. Re-run if you want to see all 4 error codes.
- **The Żabka Krakow store sync fixture is fragile.** It's the only ONBOARDING source for the tenant-side persona. If a regression test deletes it, restore by restarting dev server (fixture re-loads from JSON).
- **Don't run `./deploy-dev.sh` or `git push` during regression.** Local-only constraint still in effect.

---

## Severity guide

- **BLOCKER:** core flow broken (can't upload, can't create source, persona switching breaks chrome)
- **MAJOR:** specific feature broken but workaround exists (e.g., one source type's config form misrenders)
- **MINOR:** UX issue, console warning, visual glitch (non-blocking)

When in doubt, mark MAJOR — easier to downgrade later than to under-report.
