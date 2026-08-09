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

// THE BROWSER'S OWN IANA LIST, not a curated one. A short list would be a second
// source of truth for what zones exist and would be wrong for the first customer
// outside it.
//
// THE BROWSER'S TZ DATABASE CAN BE NEWER THAN POSTGRES'S, so this can offer a zone
// the database refuses. That is handled rather than prevented: the BFF validates with
// Python's tzdata and the provision table's BEFORE INSERT trigger validates against
// the server's own catalogue, and the trigger's message is surfaced verbatim. Three
// tz databases, and the only one that can speak for the row is the one in the
// database the row lands in.
function zoneOptions(): string[] {
  const supported = (
    Intl as unknown as { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf;
  if (typeof supported !== "function") return [];
  try {
    return supported("timeZone");
  } catch {
    return [];
  }
}

export function EnableMonitor({
  tenantId,
  analysisId,
  analysisName,
}: {
  tenantId: string;
  analysisId: string;
  analysisName: string;
}) {
  const [pending, startTransition] = useTransition();
  const [open, setOpen] = useState(false);
  const [zone, setZone] = useState<string>(NO_ZONE);
  const [error, setError] = useState<string | null>(null);
  const [warning, setWarning] = useState<string | null>(null);

  // COMPUTED ON FIRST RENDER OF THE OPEN STATE, not at module scope: Intl is a client
  // API and this file is imported by a server component's module graph.
  const zones = open ? zoneOptions() : [];

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
            <select
              value={zone}
              disabled={pending}
              onChange={(event) => setZone(event.target.value)}
              className="text-caption rounded-md border border-border bg-surface px-2 py-1.5 text-foreground"
            >
              <option value={NO_ZONE}>Choose a timezone...</option>
              {zones.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </label>

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
                setError(null);
              }}
              className="text-caption rounded-md border border-border px-3 py-1.5 text-foreground-muted hover:bg-surface-2 disabled:opacity-50"
            >
              Cancel
            </button>
            <button
              type="button"
              // Disabled until a zone is chosen. See NO_ZONE above.
              disabled={pending || zone === NO_ZONE}
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
