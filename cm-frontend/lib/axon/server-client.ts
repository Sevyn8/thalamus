// Server-side client for AXON's read surface. NEVER imported by a client component.
//
// ============================================================================
// WHY THIS FILE EXISTS AT ALL WHEN IT CALLS THE SAME SERVICE
// ============================================================================
// Axon's delivery ledger is served by synapse-ui-server today. That was decided
// on an IAM fact rather than a preference: a standalone Axon BFF would be a fifth
// HTTP service, and the only reason Axon would eventually need its own is an
// INBOUND WEBHOOK RECEIVER (provider delivery receipts), which a provider can
// only reach if the service carries `allUsers` on roles/run.invoker.
// synapse-ui-server has a terraform `lifecycle.precondition` and two tests
// refusing exactly that binding, so the webhook can never live there. When the
// inbound slice arrives it brings its own service, publicly invokable by
// necessity and holding no console credential.
//
// SO THE MODULE BOUNDARY IS DRAWN IN THE CLIENT NOW, WHILE IT IS ONE LINE. This
// file resolves AXON_BFF_URL first and falls back to SYNAPSE_BFF_URL. Today both
// resolve to the same origin and nothing is configured; the day Axon gets its own
// service, setting one environment variable moves every call in this file, and no
// page changes. A console that had reached for synapseGet would need every call
// site found and rewritten instead, which is the kind of change that gets half
// done.
//
// ============================================================================
// EVERYTHING ELSE IS THE SYNAPSE CLIENT'S, AND DELIBERATELY SO
// ============================================================================
// The two tokens, their order, the per-request env read, the session-read-first
// rule: all of it is lib/synapse/server-client.ts's, and every one of those was
// paid for once already. This file does not restate the arguments; it points at
// them, and it uses the same helpers rather than a second copy that can drift.
//
//   TWO TOKENS, TWO LAYERS. `Authorization` carries the USER's Auth0 token and
//   the BFF verifies it (which person). `X-Serverless-Authorization` carries a
//   Google ID token and Cloud Run IAM verifies it before the container sees the
//   request (which workload). Sending the Google token as `Authorization` made
//   every request 401 once; both halves were correct in isolation.
//
//   THE SESSION READ COMES FIRST. Touching cookies is what marks the route
//   dynamic. Checking config first threw before any cookie was read, Next.js
//   prerendered the page at build time, and the container served static HTML
//   saying the service was unreachable while the service was fine.
//
// ONE THING IS NOT INHERITED: there is no post helper here, and the omission is
// the design rather than an economy. axon_reader holds SELECT and no write verb
// anywhere. A write helper in this file would be a control with no credential
// behind it, and its first caller would discover that in production.

import "server-only";

import { SynapseUnavailable, synapseGetFrom } from "@/lib/synapse/server-client";

export { SynapseUnavailable };

// AXON_BFF_URL ?? SYNAPSE_BFF_URL. Read PER REQUEST, never at module scope: this
// is runtime config that must change with a revision bounce rather than a
// rebuild, and a module-scope read froze the Synapse client's base URL at BUILD
// time once already.
//
// NEITHER IS NEXT_PUBLIC_, so neither reaches the browser. That is what keeps the
// BFF unreachable from a browser at all, which is why it needs no `allUsers`
// binding and has no CORS surface to get wrong.
function axonBase(): string {
  return process.env.AXON_BFF_URL ?? process.env.SYNAPSE_BFF_URL ?? "";
}

// THE MISSING-BASE CHECK IS NOT HERE, AND ITS ABSENCE IS DELIBERATE. It lives
// inside synapseGetFrom, AFTER the session read, because a throw that fires before
// any cookie is touched lets Next.js prerender the page at build time and bake the
// error into static HTML. That happened once to the Synapse console and took a
// container inspection to find. Resolving the env here is fine; refusing here is
// not.
export async function axonGet<T>(path: string): Promise<T> {
  return synapseGetFrom<T>(
    axonBase(),
    path,
    "neither AXON_BFF_URL nor SYNAPSE_BFF_URL is configured; the delivery ledger cannot load",
  );
}

// ============================================================================
// THE SHAPES THE BFF RETURNS
// ============================================================================
// Hand-written against synapse_ui_server/main.py's GET /deliveries, which is the
// same seam every other console type crosses here: no generated client, no shared
// package, and an HTTP boundary no compiler checks. A field renamed on one side
// and not the other is a runtime undefined rendering as an empty cell.

// `scope` IS SYNTHESISED BY THE QUERY, not stored. It is the only thing that
// distinguishes a platform delivery from a tenant one in a merged list.
export type DeliveryScope = "PLATFORM" | "TENANT";

export interface DeliveryRow {
  scope: DeliveryScope;
  delivery_id: string;
  // NULL FOR EVERY PLATFORM ROW, by construction: axon.platform_deliveries has no
  // such column, because a platform delivery has no tenant.
  tenant_id: string | null;
  created_at: string;
  channel: string;
  notification_class: string;
  subject_kind: string;
  subject_id: string;
  recipient: string;
  // ACCEPTED IS NOT DELIVERED. "accepted" means a provider took the message; it
  // does not mean it arrived. There is no state that means arrived, because
  // nothing in this platform can observe one until an inbound receipt plane
  // exists.
  state: string;
  suppression_reason: string | null;
  provider: string;
  failure_detail: string | null;
  actor_subject: string | null;
}

export interface DeliveryCounts {
  total: number;
  accepted: number;
  failed: number;
  suppressed: number;
  // BROKEN OUT FROM `suppressed` DELIBERATELY. It is the one suppression reason
  // that means a client is receiving nothing while the platform believes it is
  // working. Folded into the general count it is invisible.
  suppressed_not_onboarded: number;
}

export interface DeliveriesResponse {
  deliveries: DeliveryRow[];
  // The list is capped and the counts are not. `truncated` is the page's only way
  // to say so; without it a capped page presents a floor as a total.
  truncated: boolean;
  counts: DeliveryCounts;
}

export async function fetchDeliveries(): Promise<DeliveriesResponse> {
  return axonGet<DeliveriesResponse>("/deliveries");
}
