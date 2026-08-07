"use server";

import { revalidatePath } from "next/cache";

import { synapsePost } from "@/lib/synapse/server-client";

// THE FIRST SERVER ACTION IN THIS CONSOLE, and it is server-side because it has to
// be rather than because it is tidy. Reaching the BFF needs the user's Auth0 token
// AND a Google ID token minted from the runtime service account's metadata server;
// a browser has neither, and SYNAPSE_BFF_URL is not NEXT_PUBLIC_. So there is no
// version of this that runs in the client component that calls it.
//
// READ-BACK, NOT OPTIMISM. revalidatePath re-renders the page from the BFF after the
// write. An optimistic chip that later disagreed with the server would be the page
// asserting a state it had not been told — the failure this console already has a
// rule against.

export type DecisionResult = { ok: true } | { ok: false; message: string };

export async function recordDecision(
  tenantId: string,
  eventId: string,
  body: { verb: string; reason?: string | null; snoozed_until?: string | null },
): Promise<DecisionResult> {
  try {
    await synapsePost(`/tenants/${tenantId}/alerts/${eventId}/decisions`, body);
  } catch (error) {
    // RETURNED, NOT THROWN. A thrown server action becomes the error boundary and
    // loses the BFF's message — which for a 422 is the sentence naming the legal
    // reasons, i.e. the one thing the operator can act on.
    return { ok: false, message: error instanceof Error ? error.message : "unknown error" };
  }
  revalidatePath(`/superadmin/synapse/tenants/${tenantId}/alerts/${eventId}`);
  revalidatePath(`/superadmin/synapse/tenants/${tenantId}`);
  return { ok: true };
}
