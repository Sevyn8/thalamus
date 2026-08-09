"use client";

import { useState, useTransition } from "react";

import { type EnableResult, enableMonitor } from "./actions";

// THE SECOND INTERACTIVE COMPONENT IN THE SYNAPSE CONSOLE (slice 5e). Everything else
// is a server component rendering what the BFF returned.
//
// WHAT THIS CONTROL DELIBERATELY DOES NOT OFFER, because a form discards safety
// properties by default and each omission here is one of them:
//
//   NO CADENCE, NO RUNG. Both are constants in the BFF, and a dropdown would be a
//   fleet outage waiting to be clicked: the envelope check runs when the
//   ORCHESTRATOR LOADS the provision table and refuses the WHOLE ENUMERATION, so one
//   wrong rung stops the 04:00 sweep for every tenant. The DDL permits 'suggest' and
//   nothing implements it, so a dropdown built from the CHECK constraint would offer
//   exactly the value that breaks the fleet.
//
//   NO TENANT FIELD. The tenant comes from the route, which was reached from the
//   fleet roster. An unknown tenant UUID inserts fine, enumerates fine, and produces
//   a healthy run with zero actions every day for ever with nothing going red;
//   removing the way to type one beats catching it afterwards.
//
//   NO ANALYSIS FIELD. Same shape, worse blast radius: an undeclared analysis id
//   refuses the whole enumeration for every tenant. The id comes from the registry
//   catalogue the page already rendered.
//
// SO THE ONLY THING AN OPERATOR CHOOSES IS THE TIMEZONE, and that is chosen ONCE.

// NO DEFAULT ZONE, AND THIS IS THE MOST IMPORTANT LINE IN THE FILE.
//
// The obvious default is the operator's own zone from
// Intl.DateTimeFormat().resolvedOptions().timeZone, and it is exactly wrong. This is
// the TENANT's REPORTING timezone, not the person's: an operator in London enabling a
// monitor for an Indian retailer would get Europe/London preselected, the form would
// look complete, and every slot boundary and every action's as_of would be five and a
// half hours out. Nothing would fail. It would simply be wrong for ever, because the
// zone sits inside an append-only idempotency index that cannot be re-keyed.
//
// So the select starts empty and Enable stays disabled until a zone is picked. Same
// pattern and same reasoning as the dismiss-reason radios on the alert detail page: a
// default would make the commonest value the one nobody meant.
const NO_ZONE = "";

// ============================================================================
// THE LIST COMES FROM THE BFF. THE COMMENT THAT USED TO BE HERE IS WHY.
// ============================================================================
// This block held a zoneOptions() reading Intl.supportedValuesOf("timeZone"),
// under a comment that said:
//
//   "THE BROWSER'S TZ DATABASE CAN BE NEWER THAN POSTGRES'S, so this can offer a
//    zone the database refuses. That is handled rather than prevented."
//
// BOTH HALVES WERE WRONG, and the comment is corrected here rather than deleted
// with the code, because it is the artifact that caused the outage and its
// correction is the lesson.
//
//   WRONG ABOUT WHO DISAGREED. The disagreement that bit was the browser versus
//   PYTHON, not the browser versus Postgres. The BFF runs on python:3.12-slim,
//   whose Debian tzdata carries the canonical IANA names and OMITS the
//   backward-compatibility links.
//
//   WRONG ABOUT WHICH WAY IT WOULD FAIL. Postgres would have ACCEPTED the value.
//   The browser resolves identifiers through CLDR/ICU, which treats
//   Asia/Calcutta as canonical and Asia/Kolkata as the alias, the reverse of
//   IANA. So the picker offered Asia/Calcutta, did not offer Asia/Kolkata at
//   all, and every enable was refused by the BFF at validation. Every tenant in
//   production is Asia/Kolkata. The control could not emit the only value
//   anybody needed.
//
//   AND "HANDLED RATHER THAN PREVENTED" WAS THE ACTUAL MISTAKE. It named a real
//   hazard and then chose to catch it downstream. Downstream is after the
//   operator has committed, on a column that is immutable.
//
// THE INTERSECTION REVERSES ALL THREE. The BFF serves the names that BOTH its
// own zoneinfo and the Postgres it writes to accept, computed at startup. An
// intersection cannot contain a name either side rejects, so "offered" and
// "writable" are the same set by construction rather than by review. See
// synapse_ui_server/timezones.py, which also records why this defect does not
// reproduce on a devbox.
//
// SO THIS COMPONENT NO LONGER TOUCHES Intl, AND MUST NOT AGAIN. It renders the
// list it is given. A browser-derived list is a fourth timezone database that
// nobody validates against.

// GROUPED BY THE PREFIX BEFORE THE SLASH, which is derived mechanically from the
// name and so invents nothing. Roughly 486 entries in one flat alphabetical list is
// a control designed to be got wrong, especially when a deprecated-looking alias can
// sort near the answer.
//
// DELIBERATELY NOT A "COMMON ZONES" GROUP PINNED AT THE TOP. That needs a hardcoded
// list, which is the second source of truth this file's original comment correctly
// argued against; "every tenant is Asia/Kolkata" is a fact about today's customers
// rather than a property of the system; and putting the likely answer under the
// operator's thumb is one edit away from re-creating the default that NO_ZONE exists
// to prevent.
function byRegion(zones: string[]): Array<[string, string[]]> {
  const groups = new Map<string, string[]>();
  for (const name of zones) {
    const slash = name.indexOf("/");
    const region = slash === -1 ? "Other" : name.slice(0, slash);
    const existing = groups.get(region);
    if (existing) existing.push(name);
    else groups.set(region, [name]);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export function EnableMonitor({
  tenantId,
  analysisId,
  analysisName,
  zones,
  zoneSource,
}: {
  tenantId: string;
  analysisId: string;
  analysisName: string;
  // Served by the BFF, never derived here. Empty means the list could not be loaded,
  // and the page does not render this component at all in that case.
  zones: string[];
  // "intersection" or "python_only". See the degraded note below.
  zoneSource: string;
}) {
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [zone, setZone] = useState<string>(NO_ZONE);
  const [filter, setFilter] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  // SUBSTRING ON THE WHOLE NAME, case-insensitive, so "kol", "asia/kol" and "kolkata"
  // all find Asia/Kolkata. Filtering rather than a combobox because a native select
  // stays keyboard- and screen-reader-correct without a dependency.
  const needle = filter.trim().toLowerCase();
  const matching = needle ? zones.filter((n) => n.toLowerCase().includes(needle)) : zones;
  const grouped = byRegion(matching);

  // THE FILTER MUST NOT SILENTLY DROP A CHOSEN ZONE. Typing on after picking one would
  // otherwise leave `zone` set to something no longer in the list, and Enable would
  // stay armed against an option the operator can no longer see.
  const chosenIsVisible = zone === NO_ZONE || matching.includes(zone);

  function send() {
    setError(null);
    setWarning(null);
    startTransition(async () => {
      const result: EnableResult = await enableMonitor(tenantId, analysisId, zone);
      if (!result.ok) {
        setError(result.message);
        return;
      }
      // The action revalidates, so the page re-renders from the reader and the
      // monitor moves into the enabled list on its own. Nothing here claims it did.
      setWarning(result.warning);
      setOpen(false);
    });
  }

  return (
    <div className="text-right">
      {!open ? (
        <button
          type="button"
          onClick={() => setOpen(true)}
          className="text-caption rounded-md border border-border px-3 py-1.5 text-foreground hover:bg-surface-2"
        >
          Enable
        </button>
      ) : (
        <div className="flex flex-col items-end gap-2">
          <label className="text-caption flex flex-col items-end gap-1 text-foreground-muted">
            Reporting timezone for this client
            <input
              type="text"
              value={filter}
              disabled={pending}
              onChange={(event) => setFilter(event.target.value)}
              placeholder="Search, e.g. Kolkata"
              className="text-caption w-64 rounded-md border border-border bg-surface px-2 py-1.5 text-foreground"
            />
          </label>

          {matching.length === 0 ? (
            /* THE EMPTY STATE CARRIES THE ALIAS EXPLANATION, because "no results" for
               a real city name is otherwise inexplicable. It says the shape of the
               problem without a mapping table: naming Calcutta-to-Kolkata here would
               be the same second source of truth, and one step from translating. */
            <p className="text-micro max-w-xs text-right text-foreground-subtle">
              No timezone matches &quot;{filter}&quot;. Deprecated IANA aliases, including some
              older city spellings, are deliberately not offered. Try the current name, or search
              by a nearby city.
            </p>
          ) : (
            <select
              // NAMED EXPLICITLY. The visible label above now belongs to the search
              // input that precedes it, so without this the select is an unnamed
              // control to a screen reader: the one input on the whole enable flow,
              // announced as nothing.
              aria-label="Reporting timezone for this client"
              value={chosenIsVisible ? zone : NO_ZONE}
              disabled={pending}
              onChange={(event) => setZone(event.target.value)}
              className="text-caption w-64 rounded-md border border-border bg-surface px-2 py-1.5 text-foreground"
            >
              <option value={NO_ZONE}>Choose a timezone...</option>
              {grouped.map(([region, names]) => (
                <optgroup key={region} label={region}>
                  {names.map((name) => (
                    <option key={name} value={name}>
                      {name}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          )}

          {/* THE COUNT, so the operator can see the filter biting rather than
              wondering whether the list is short or the search is wrong. */}
          <p className="text-micro text-right text-foreground-subtle">
            {needle
              ? `${matching.length} of ${zones.length} zones`
              : `${zones.length} zones offered`}
          </p>

          {/* THE DEGRADED PATH, SAID PLAINLY AND QUIETLY. python_only means the BFF
              could not read Postgres at startup, so this list is its own names alone
              and a zone on it may still be refused by the table's trigger, after the
              operator has committed. A console that knows that and stays silent is
              worse than one that says it. */}
          {zoneSource === "python_only" && (
            <p className="text-micro max-w-xs text-right text-foreground-subtle">
              This list could not be checked against the database and may offer a zone the
              database refuses. If enabling fails on the timezone, that is why.
            </p>
          )}

          {/* SAID BEFORE THE CLICK, NOT AFTER. The zone cannot be changed once a
              monitor is enabled, and an operator who learns that from an error
              message has already made the choice. */}
          <p className="text-micro max-w-xs text-right text-foreground-subtle">
            Chosen once. This decides what &quot;today&quot; means for {analysisName} and cannot be
            changed afterwards. It is the client&apos;s reporting zone, not yours and not any one
            store&apos;s.
          </p>

          <div className="flex gap-2">
            <button
              type="button"
              disabled={pending}
              onClick={() => {
                setOpen(false);
                setZone(NO_ZONE);
                setFilter("");
                setError(null);
              }}
              className="text-caption rounded-md border border-border px-3 py-1.5 text-foreground-muted hover:bg-surface-2 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              // Disabled until a zone is chosen, and disabled again if the filter has
              // since hidden it. See NO_ZONE above.
              disabled={pending || zone === NO_ZONE || !chosenIsVisible}
              onClick={send}
              className="text-caption rounded-md border border-border px-3 py-1.5 text-foreground hover:bg-surface-2 disabled:opacity-50"
            >
              {pending ? "Enabling..." : "Enable in silent mode"}
            </button>
          </div>
        </div>
      )}

      {error && (
        <p className="text-caption mt-2 max-w-md text-left text-warning" role="alert">
          {error}
        </p>
      )}

      {/* A WARNING, RENDERED AS ONE, NOT AS A FAILURE. The monitor IS enabled. This
          says the client has no canonical positions yet, which is legitimate before
          ingestion and is worth saying so that a week of empty runs is not read as a
          broken monitor. */}
      {warning && (
        <p className="text-caption mt-2 max-w-md text-left text-foreground-muted">{warning}</p>
      )}
    </div>
  );
}
