"use client";

import { useState } from "react";
import { Plus, Trash2 } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import { ApiError } from "@/lib/api/client";
import {
  CHANNEL_KINDS,
  CREDENTIAL_KEY_PATTERN,
  MAX_CREDENTIAL_BLOB_BYTES,
  MAX_CREDENTIAL_PAIRS,
  MAX_CREDENTIAL_VALUE_LENGTH,
  MAX_PROVIDER_LENGTH,
  MAX_SENDING_IDENTITY_LENGTH,
  type ChannelKind,
} from "@/lib/api/channels";
import { useUpsertChannel } from "@/lib/hooks/use-channels";

// The form a tenant administrator uses to configure their OWN sending channel.
//
// =========================================================================
// IT HAS NO READ PATH, AND THAT IS THE DESIGN RATHER THAN A MISSING FEATURE
// =========================================================================
// There is no "load current credential and edit it" here because there is
// nothing to load. cm-backend's IAM role omits secretmanager.versions.access,
// so the service cannot read a stored credential back, and its read model
// (ChannelConnectionRead) has no field for one. A partial edit would need a
// stored set to merge into. So every save REPLACES the whole set, the inputs
// start empty every time, and the form says so above the inputs rather than
// letting a tenant discover it by losing a value.
//
// This is also why the inputs are never populated from a response anywhere in
// this file. scripts/assert-channel-credential-safety.mjs fails the build if
// the read type ever gains a field that could pre-fill them.
//
// =========================================================================
// KEY-VALUE PAIRS RATHER THAN NAMED FIELDS, AND NO SEEDED NAMES AT ALL
// =========================================================================
// This form used to seed three rows named client_id, username and password.
// Those are the values in hand for ONE provider, and it is the odd one: they
// match none of Sinch's documented current APIs. Worse, every channel will have
// its own field set. WhatsApp, SMS, email and a voicebot will not agree with
// each other, so any seed chosen now is wrong for most of them and teaches a
// default that does not hold.
//
// So there is ONE EMPTY ROW and no vocabulary. The tenant enters what their
// provider gave them, which is the same reason the backend's schema validates
// SHAPE and never semantics. A per-provider field schema belongs with the
// adapter work, where something will actually consume the names.

type Pair = { id: string; key: string; value: string };

let pairCounter = 0;

function newPair(): Pair {
  pairCounter += 1;
  return { id: `pair-${pairCounter}`, key: "", value: "" };
}

// One row, empty, named nothing. Also the reset shape after a successful save.
function seedPairs(): Pair[] {
  return [newPair()];
}

function blobBytes(pairs: Pair[]): number {
  const object: Record<string, string> = {};
  for (const p of pairs) object[p.key] = p.value;
  return new TextEncoder().encode(JSON.stringify(object)).length;
}

// Mirrors cm-backend/src/admin_backend/schemas/channel.py. The server is the
// boundary and re-checks all of this; mirroring it means a mistake surfaces
// next to the offending row instead of as a 422 that discards a credential set
// the tenant just retyped in full.
function validate(args: {
  channel: ChannelKind;
  provider: string;
  sendingIdentity: string;
  pairs: Pair[];
}): string[] {
  const problems: string[] = [];
  const provider = args.provider.trim();

  if (!provider) problems.push("Enter the provider's name.");
  if (provider.length > MAX_PROVIDER_LENGTH) {
    problems.push(`Provider must be ${MAX_PROVIDER_LENGTH} characters or fewer.`);
  }
  if (args.sendingIdentity.length > MAX_SENDING_IDENTITY_LENGTH) {
    problems.push(
      `Sending identity must be ${MAX_SENDING_IDENTITY_LENGTH} characters or fewer.`,
    );
  }

  // MIRRORS THE SERVER, WHICH ENFORCES. The rule is per-channel and only email has one: the
  // identity there IS the From address, so it is an email address. sms and whatsapp get no
  // format rule because an E.164 number and an alphanumeric sender id are both legitimate and
  // which one a tenant may use is the provider's rule, not ours. Guessing a pattern would
  // refuse valid input with a confident message.
  //
  // A phone number saved on an email channel is what this closes; it happened on 2026-08-15.
  //
  // DELIBERATELY LOOSER THAN THE SERVER'S EmailStr. This exists to put the message next to the
  // field instead of after a round trip, so it catches the obvious case and lets the server be
  // the authority on the edges. A client check that tried to be exact would start refusing
  // addresses the server accepts, which is a dead control of the worst kind: one that is wrong.
  const identity = args.sendingIdentity.trim();
  if (args.channel === "email" && identity && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(identity)) {
    problems.push(
      "Sending identity must be an email address on an email channel. It is the From address your recipients will see.",
    );
  }

  const filled = args.pairs.filter((p) => p.key.trim() || p.value);
  if (filled.length === 0) {
    problems.push("Enter at least one credential value.");
  }
  if (filled.length > MAX_CREDENTIAL_PAIRS) {
    problems.push(`No more than ${MAX_CREDENTIAL_PAIRS} credential rows.`);
  }

  for (const p of filled) {
    const key = p.key.trim();
    if (!key) {
      problems.push("Every credential row needs a name.");
      continue;
    }
    if (!CREDENTIAL_KEY_PATTERN.test(key)) {
      problems.push(
        `"${key}" is not a usable name. Use letters, digits, dot, dash or underscore, and no spaces.`,
      );
    }
    if (!p.value) problems.push(`Enter a value for "${key}".`);
    if (p.value.length > MAX_CREDENTIAL_VALUE_LENGTH) {
      problems.push(`The value for "${key}" is too long.`);
    }
  }

  // Refused rather than last-wins, exactly as the server refuses it: storing a
  // duplicate would silently drop one of the tenant's values, and the dropped
  // one is invisible from this form.
  const keys = filled.map((p) => p.key.trim()).filter(Boolean);
  const duplicates = [...new Set(keys.filter((k, i) => keys.indexOf(k) !== i))];
  for (const d of duplicates) problems.push(`"${d}" is entered twice.`);

  if (blobBytes(filled) > MAX_CREDENTIAL_BLOB_BYTES) {
    problems.push("The credential set is too large to store.");
  }

  return problems;
}

export function ChannelCredentialForm() {
  const [channel, setChannel] = useState<ChannelKind>("whatsapp");
  const [provider, setProvider] = useState("");
  const [sendingIdentity, setSendingIdentity] = useState("");
  const [pairs, setPairs] = useState<Pair[]>(seedPairs);
  const [problems, setProblems] = useState<string[]>([]);

  const upsert = useUpsertChannel();

  function updatePair(id: string, patch: Partial<Pair>) {
    setPairs((current) =>
      current.map((p) => (p.id === id ? { ...p, ...patch } : p)),
    );
  }

  function removePair(id: string) {
    setPairs((current) => current.filter((p) => p.id !== id));
  }

  function handleSubmit(event: React.FormEvent) {
    event.preventDefault();

    const found = validate({ channel, provider, sendingIdentity, pairs });
    setProblems(found);
    if (found.length > 0) return;

    const credential = pairs
      .filter((p) => p.key.trim() && p.value)
      .map((p) => ({ key: p.key.trim(), value: p.value }));

    upsert.mutate(
      {
        channel,
        provider: provider.trim(),
        sending_identity: sendingIdentity.trim() || null,
        credential,
      },
      {
        onSuccess: (saved) => {
          // CLEARED ON SUCCESS, deliberately. Leaving the values in component
          // state keeps a live credential in the page for as long as the tab
          // stays open, and the form cannot re-read them anyway, so there is
          // nothing to keep them for.
          setPairs(seedPairs());
          setProvider("");
          setSendingIdentity("");
          setProblems([]);

          // THE TOAST USED TO SAY "the previous credential was replaced" ON EVERY SAVE,
          // INCLUDING THE FIRST, when there was no previous credential to replace. A message
          // asserting an event that did not happen is the same defect as a control that does
          // nothing, and this one is worse than it looks: replacement is the property the whole
          // surface warns about, so claiming it on a first save teaches the tenant to distrust
          // the warning that matters.
          //
          // GROUNDED IN WHAT THE WRITE RETURNED, not in what the page had loaded. The upsert
          // sets created_at and updated_at from the same now() on INSERT and leaves created_at
          // alone in the ON CONFLICT branch, so equality means this row was created by this
          // request. The loaded list would also answer the question and can be stale or
          // partially loaded; the response cannot.
          const wasCreated = saved.created_at === saved.updated_at;
          toast.success(
            wasCreated
              ? "Channel saved."
              : "Channel saved. The previous credential was replaced.",
          );
        },
        onError: (error) => {
          // Never echoes a submitted value. The 401 case is called out because
          // it is the one where the tenant has just retyped an entire
          // credential set and needs to know it did not land.
          if (error instanceof ApiError && error.status === 401) {
            toast.error("Your session expired. Nothing was saved. Sign in and enter the credential again.");
            return;
          }
          const message =
            error instanceof ApiError ? error.message : "The channel could not be saved.";
          toast.error(message);
        },
      },
    );
  }

  const rowLimitReached = pairs.length >= MAX_CREDENTIAL_PAIRS;

  return (
    <form onSubmit={handleSubmit} className="flex flex-col gap-6">
      {/* THE REPLACEMENT WARNING SITS ABOVE THE INPUTS, not in fine print
          underneath them. A tenant who reads it after typing has already
          decided what to type. */}
      <div className="rounded-md border border-[var(--warning-line,var(--border))] bg-warning/5 p-4 text-sm">
        <p className="text-body-strong">Saving replaces the whole credential.</p>
        <p className="mt-1 text-muted-foreground">
          Sevyn8 stores your credential but can never read it back, so there is
          nothing to edit in place. Every value has to be entered again each time
          you save, including the ones you are not changing.
        </p>
      </div>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div className="flex flex-col gap-2">
          <label htmlFor="channel-kind" className="text-label">
            Channel
          </label>
          <select
            id="channel-kind"
            value={channel}
            onChange={(e) => setChannel(e.target.value as ChannelKind)}
            className={cn(
              "h-8 w-full rounded-md border border-input bg-background px-2.5 py-1 text-sm",
              "focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 focus-visible:outline-none",
            )}
          >
            {CHANNEL_KINDS.map((k) => (
              <option key={k} value={k}>
                {k}
              </option>
            ))}
          </select>
        </div>

        <div className="flex flex-col gap-2">
          <label htmlFor="channel-provider" className="text-label">
            Provider
          </label>
          <Input
            id="channel-provider"
            value={provider}
            onChange={(e) => setProvider(e.target.value)}
            maxLength={MAX_PROVIDER_LENGTH}
            placeholder="who you buy the channel from"
            autoComplete="off"
          />
        </div>
      </div>

      {/* SEPARATE AND PLAINLY LABELLED, and the copy says who can see it. It is
          an identifier, not a secret, and conflating the two either overstates
          the protection on this field or understates it on the credential. */}
      <div className="flex flex-col gap-2">
        <label htmlFor="channel-sending-identity" className="text-label">
          Sending identity
        </label>
        <Input
          id="channel-sending-identity"
          value={sendingIdentity}
          onChange={(e) => setSendingIdentity(e.target.value)}
          maxLength={MAX_SENDING_IDENTITY_LENGTH}
          placeholder={
            channel === "email"
              ? "the address your recipients will see in the From line"
              : "the number or sender id your recipients will see"
          }
          autoComplete="off"
        />
        {/* THE COPY IS PER CHANNEL, because the old copy was not. It said "the number or sender
            id" on every channel including email, which is how a phone number came to be saved
            as an email From address.

            IT ALSO SAYS WHERE A RULE EXISTS AND WHERE ONE DOES NOT. Claiming a format is
            enforced on sms would be the same defect in the other direction: the tenant would
            read a checked field and get an unchecked one. */}
        <p className="text-caption text-muted-foreground">
          {channel === "email"
            ? "The From address your recipients will see. It has to be an email address."
            : "The number or sender id your recipients will see. Your provider decides what is valid here, so we do not check the format."}{" "}
          Not a secret. Sevyn8 support can see this, unlike the credential below.
        </p>
      </div>

      <div className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h3 className="text-subheading">Credential</h3>
          <p className="text-caption text-muted-foreground">
            Enter the field names exactly as your provider gave them, and add a
            row for each one. Different providers use different names, and the
            same provider often uses different names for different channels, so
            there is nothing here to fill in for you.
          </p>
        </div>

        <div className="flex flex-col gap-2">
          {pairs.map((pair) => (
            <div key={pair.id} className="flex items-center gap-2">
              <Input
                aria-label="Credential name"
                value={pair.key}
                onChange={(e) => updatePair(pair.id, { key: e.target.value })}
                placeholder="name"
                className="max-w-[220px]"
                autoComplete="off"
              />
              {/* type="password" IS A LITERAL AND THERE IS NO REVEAL CONTROL.
                  A show/hide toggle would make this an expression, which is
                  what the build guard refuses. autoComplete="new-password"
                  keeps a browser password manager from offering to store
                  another company's provider credential; it reduces that and
                  cannot eliminate it. */}
              <Input
                aria-label="Credential value"
                type="password"
                value={pair.value}
                onChange={(e) => updatePair(pair.id, { value: e.target.value })}
                placeholder="value"
                autoComplete="new-password"
                maxLength={MAX_CREDENTIAL_VALUE_LENGTH}
              />
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label="Remove this credential row"
                onClick={() => removePair(pair.id)}
              >
                <Trash2 />
              </Button>
            </div>
          ))}
        </div>

        <div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => setPairs((c) => [...c, newPair()])}
            disabled={rowLimitReached}
          >
            <Plus />
            Add a row
          </Button>
          {rowLimitReached ? (
            <span className="ml-3 text-caption text-muted-foreground">
              {MAX_CREDENTIAL_PAIRS} rows is the maximum.
            </span>
          ) : null}
        </div>
      </div>

      {problems.length > 0 ? (
        <div
          role="alert"
          className="rounded-md border border-destructive/40 bg-destructive/5 p-4 text-sm"
        >
          <p className="text-body-strong">This has not been saved.</p>
          <ul className="mt-2 list-disc pl-5 text-muted-foreground">
            {problems.map((p) => (
              <li key={p}>{p}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="flex items-center gap-3">
        <Button type="submit" disabled={upsert.isPending}>
          {upsert.isPending ? "Saving..." : "Save channel"}
        </Button>
        <span className="text-caption text-muted-foreground">
          Saving stores the credential and replaces what was there before.
        </span>
      </div>
    </form>
  );
}
