import { apiFetch } from "./client";
import type { components } from "@/types/openapi-generated";

// Tenant sending channels. Three backend routes, two audiences, one table.
//
//   GET  /api/v1/channels           the caller's OWN tenant's connections
//   PUT  /api/v1/channels           configure or reconfigure one channel
//   GET  /api/v1/channels/platform  every tenant's connection state (operator)
//
// NOTHING HERE CAN READ A CREDENTIAL BACK, and that is a property of the estate
// rather than of this file. cm-backend's IAM role (cmChannelVaultWriter) omits
// secretmanager.versions.access, so the service itself cannot read a stored
// credential; ChannelConnectionRead accordingly has no field for one. The write
// type carries values and the read type does not, and the asymmetry is the point.
// Do not "tidy" them into a shared shape.
//
// NO Idempotency-Key ON THE WRITE, unlike stores.ts and onboarding.ts, and the
// difference is reasoned rather than an omission. Those are CREATEs, where a
// retry after a 500 mints a second row and the key is what collapses the two
// intents. This is an upsert on the natural key (tenant_id, channel): a retry
// converges on the same row and the same deterministic secret name, so a key
// would be a header nothing reads protecting against nothing.

export type ChannelConnectionRead =
  components["schemas"]["ChannelConnectionRead"];
export type ChannelConnectionsListResponse =
  components["schemas"]["ChannelConnectionsListResponse"];
export type ChannelCredentialPair =
  components["schemas"]["ChannelCredentialPair"];
export type ChannelUpsertRequest =
  components["schemas"]["ChannelUpsertRequest"];
export type PlatformChannelConnectionRead =
  components["schemas"]["PlatformChannelConnectionRead"];
export type PlatformChannelConnectionsListResponse =
  components["schemas"]["PlatformChannelConnectionsListResponse"];

// The ledger's CHECK vocabulary. cm-backend re-validates it and answers 422
// naming the field, so this exists to keep the picker honest, not to enforce.
export const CHANNEL_KINDS = ["email", "whatsapp", "sms"] as const;
export type ChannelKind = (typeof CHANNEL_KINDS)[number];

// Server-side shape limits, mirrored so a mistake is inline instead of a 422
// that discards a credential set the tenant just retyped in full. Sourced from
// cm-backend/src/admin_backend/schemas/channel.py; if they drift, the server
// still wins and the user sees its message.
export const CREDENTIAL_KEY_PATTERN = /^[A-Za-z0-9_.-]{1,64}$/;
export const MAX_CREDENTIAL_PAIRS = 20;
export const MAX_CREDENTIAL_VALUE_LENGTH = 4096;
export const MAX_CREDENTIAL_BLOB_BYTES = 8192;
export const MAX_PROVIDER_LENGTH = 32;
export const MAX_SENDING_IDENTITY_LENGTH = 255;

export const channelsApi = {
  // The caller's own tenant. Takes no tenant id: the tenant is in the token and
  // RLS scopes the rows. A caller that could pass one could pass the wrong one.
  mine: () => apiFetch<ChannelConnectionsListResponse>(`/api/v1/channels`),

  // Replaces the whole credential set for one channel. Returns the connection
  // row, which never carries a credential.
  upsert: (payload: ChannelUpsertRequest) =>
    apiFetch<ChannelConnectionRead>(`/api/v1/channels`, {
      method: "PUT",
      body: JSON.stringify(payload),
    }),

  // Operator fleet view. PLATFORM audience, pinned server-side.
  platform: () =>
    apiFetch<PlatformChannelConnectionsListResponse>(
      `/api/v1/channels/platform`,
    ),
};
