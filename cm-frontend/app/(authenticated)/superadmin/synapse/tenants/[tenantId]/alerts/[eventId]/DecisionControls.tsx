"use client";

import { useState, useTransition } from "react";

import { BUTTON_CLASS } from "@/components/synapse/primitives";

import { type DecisionResult, recordDecision } from "./actions";

// THE ONLY INTERACTIVE COMPONENT IN THE SYNAPSE CONSOLE. Everything else is a
// server component rendering what the BFF returned.
//
// NO DEAD CONTROLS, WHICH IS WHY THIS ARRIVES WITH 5d AND NOT WITH 5c. The detail
// page shipped with no buttons at all rather than disabled ones, because a control
// that does nothing is a promise the data could not keep. These do something.
//
// DISMISS CANNOT BE FIRED WITHOUT A REASON, and that is enforced three times over:
// the radio group has no default, the button is disabled until one is picked, and
// both the BFF and a CHECK constraint refuse an unlabelled dismissal. The reason is
// a false-positive training label — the whole value of asking is that it is always
// there and always from the closed set.

const DISMISS_REASONS: ReadonlyArray<{ value: string; label: string; hint: string }> = [
  { value: "seasonal", label: "Seasonal", hint: "Expected to be quiet at this time of year" },
  { value: "display_stock", label: "Display stock", hint: "Held for display, not for sale" },
  { value: "discontinued", label: "Discontinued", hint: "No longer stocked; will not move again" },
  { value: "wrong_data", label: "Wrong data", hint: "The numbers behind this alert are not right" },
];

const SNOOZE_DAYS = [7, 30] as const;

// Date-only, computed here so the value posted is the one the operator was shown.
function isoInDays(days: number): string {
  const when = new Date();
  when.setUTCDate(when.getUTCDate() + days);
  return when.toISOString().slice(0, 10);
}

export function DecisionControls({
  tenantId,
  eventId,
}: {
  tenantId: string;
  eventId: string;
}) {
  const [pending, startTransition] = useTransition();
  const [reason, setReason] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function send(body: { verb: string; reason?: string | null; snoozed_until?: string | null }) {
    setError(null);
    startTransition(async () => {
      const result: DecisionResult = await recordDecision(tenantId, eventId, body);
      // The server action revalidates on success, so the page re-renders from the
      // BFF and the state chip comes back from the database rather than from here.
      if (!result.ok) setError(result.message);
    });
  }

  return (
    <div>
      <div className="flex flex-wrap items-center gap-2">
        {/* BUTTON_CLASS, THE SHARED RECIPE (B3). Every button here hand-rolled its own
            `rounded border border-border ... hover:bg-surface-raised`, which matched neither of
            the two control recipes the mockups define: it moved a BACKGROUND where `.btn` moves
            a border and an accent, on a plain border where `.btn` uses the strong one. Two files
            agreeing by coincidence is how a recipe drifts, so there is now one.

            THAT HOVER WAS DEAD BEFORE B2, and the history is worth keeping: these buttons
            carried `hover:bg-surface-2`, which has no --color-surface-2 behind it, so Tailwind
            emitted no rule and they had no hover at all. Verified then against the compiled CSS
            and re-verified in B3. A class that silently does nothing is the same failure class
            as a comment that is silently false. */}
        {SNOOZE_DAYS.map((days) => (
          <button
            key={days}
            type="button"
            disabled={pending}
            onClick={() => send({ verb: "snooze", snoozed_until: isoInDays(days) })}
            className={BUTTON_CLASS}
          >
            Snooze {days}d
          </button>
        ))}
        <button
          type="button"
          disabled={pending}
          onClick={() => send({ verb: "acknowledge" })}
          className={BUTTON_CLASS}
        >
          Acknowledge
        </button>
      </div>

      {/* NATIVE <details>, the same disclosure this console already uses on Atlas
          rather than a modal primitive that does not exist here. Dismiss is behind
          it because it is the only one of the three that asks a question. */}
      <details className="mt-3">
        <summary className="text-caption cursor-pointer text-foreground-muted hover:text-foreground">
          Dismiss this alert…
        </summary>
        <fieldset className="mt-2 border-0 p-0">
          <legend className="text-caption text-foreground-muted">
            Why is this not worth acting on? The answer is recorded as a label, so these four are
            the only choices.
          </legend>
          <div className="mt-2 flex flex-col gap-1.5">
            {DISMISS_REASONS.map((option) => (
              <label key={option.value} className="text-caption flex items-start gap-2 text-foreground">
                <input
                  type="radio"
                  name="dismiss-reason"
                  value={option.value}
                  checked={reason === option.value}
                  onChange={() => setReason(option.value)}
                  className="mt-1"
                />
                <span>
                  {option.label}
                  <span className="block text-foreground-muted">{option.hint}</span>
                </span>
              </label>
            ))}
          </div>
          <button
            type="button"
            // NO DEFAULT REASON, so this stays disabled until one is chosen. A
            // default would make the commonest label the one nobody meant.
            disabled={pending || reason === null}
            onClick={() => send({ verb: "dismiss", reason })}
            className={`${BUTTON_CLASS} mt-3`}
          >
            Dismiss
          </button>
        </fieldset>
      </details>

      {error && (
        <p className="text-caption mt-2 text-warning" role="alert">
          {error}
        </p>
      )}
    </div>
  );
}
