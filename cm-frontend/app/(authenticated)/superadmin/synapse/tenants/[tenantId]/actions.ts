"use server";

import { revalidatePath } from "next/cache";

import { synapsePost } from "@/lib/synapse/server-client";

// THE SECOND SERVER ACTION IN THIS CONSOLE (slice 5e), and server-side for the same
// reason as the first rather than for tidiness. Reaching the BFF needs the user's
// Auth0 token AND a Google ID token minted from the runtime service account's
// metadata server; a browser has neither, and SYNAPSE_BFF_URL is not NEXT_PUBLIC_.
//
// READ-BACK, NOT OPTIMISM, and here it is load-bearing rather than stylistic. The
// provisioning credential holds no SELECT on the table it writes, so the BFF cannot
// tell an insert from an ON CONFLICT suppression; a 201 means "the statement ran",
// never "a row appeared". revalidatePath re-renders the page from the reader, which
// is the only thing that can say what is actually true. An optimistic chip here
// would be the page asserting a state nothing measured.
//
// ENABLE ONLY. There is deliberately no disable action and no re-enable action in
// this file. synapse.provision holds ONE window per (tenant, analysis), so clearing
// disabled_at loses the fact that there was a gap and the attribution denominator
// for that period silently becomes wrong. The BFF refuses both, the grant has no
// UPDATE, and their absence here is the third layer rather than the only one.

export type EnableResult = { ok: true; warning: string | null } | { ok: false; message: string };

export async function enableMonitor(
  tenantId: string,
  analysisId: string,
  timezone: string,
): Promise<EnableResult> {
  let warning: string | null = null;
  try {
    const response = await synapsePost<{ warning: string | null }>(
      `/tenants/${tenantId}/analyses/${analysisId}/enable`,
      { timezone },
    );
    // THE WARNING IS NOT AN ERROR AND MUST NOT RENDER AS ONE. A tenant with no
    // canonical positions is a legitimate thing to enable ahead of ingestion; the
    // reason to surface it is that a monitor producing nothing for a week is
    // otherwise indistinguishable from one that is working and finding nothing.
    warning = response.warning ?? null;
  } catch (error) {
    // RETURNED, NOT THROWN, matching the alert-decision action. A thrown server
    // action becomes the error boundary and loses the BFF's message, which for a
    // 409 on a disabled pair is the sentence explaining that re-enabling is
    // deliberately unavailable and why, and for a 422 is the timezone trigger's own
    // text naming the value it refused.
    return { ok: false, message: error instanceof Error ? error.message : "unknown error" };
  }

  // BOTH PATHS THE ENABLE CHANGES. The tenant page renders the monitor lists, and
  // the fleet roster counts analyses_running per tenant, so leaving it stale would
  // show a client with one fewer monitor than it has the moment the operator
  // navigates back.
  revalidatePath(`/superadmin/synapse/tenants/${tenantId}`);
  revalidatePath("/superadmin/synapse");
  return { ok: true, warning };
}
