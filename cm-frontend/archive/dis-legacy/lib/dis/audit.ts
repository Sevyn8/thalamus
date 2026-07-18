import { disApiFetch } from "@/lib/dis/api/client";
import { getAuthSnapshot } from "@/lib/auth/auth-cache";

// Phase 5c.2c2 generalized audit infrastructure. Originally introduced
// in 5c.1c for PII raw-view tracking; refactored at the second-and-third
// caller threshold (admin force-pause + admin reassign-ownership) to
// a generic recordAuditEvent dispatcher with a discriminated event-type
// union. Real audit publishing (push to Ithina's audit trunk so
// /superadmin/audit shows DIS events) lands in Phase 5e cutover blockers.
//
// Each event_type carries the actor (user_id + user_name + occurred_at,
// auto-populated from the persona snapshot) plus type-specific payload
// fields. The MSW endpoint /api/v1/dis/audit-events accepts any of
// these shapes and returns 204; real backend will likely accept the
// same union with stricter validation.

type ActorFields = {
  user_id: string;
  user_name: string;
  occurred_at: string;
};

export type AuditEventInput =
  | {
      event_type: "pii_viewed";
      upload_id: string;
      revealed_columns: string[];
    }
  | {
      event_type: "admin_force_pause";
      source_id: string;
      source_name: string;
      source_tenant_id: string;
    }
  | {
      event_type: "admin_reassign_ownership";
      source_id: string;
      source_name: string;
      previous_owner_user_id: string | null;
      new_owner_user_id: string;
    }
  | {
      event_type: "canonical_schema_edit";
      domain_id: string;
      field_id: string;
      classification: "additive" | "breaking" | "neutral";
      reasons: string[];
      // Captured fields that changed, before/after for audit replay.
      // Free-form record so the audit dispatcher doesn't couple to
      // the canonical-schema field shape; real backend will likely
      // structure this with a typed diff.
      changes: Record<string, { before: unknown; after: unknown }>;
    }
  | {
      // Phase 5c.8b2: a new canonical field was created.
      event_type: "canonical_schema_field_added";
      domain_id: string;
      field_id: string;
      field_name: string;
    }
  | {
      // Phase 5c.8b2: domain version was bumped, committing all
      // pending field overrides + new fields. 5c.8b3's audit panel
      // will render this richly with the change_count + kind.
      event_type: "canonical_schema_version_bumped";
      domain_id: string;
      prev_version: string;
      next_version: string;
      change_count: number;
      kind: "additive" | "breaking" | "neutral";
    }
  | {
      // Phase 5c.8e2: monthly LLM cost budget set/updated. prev_
      // budget_usd is null when no budget existed before (first-set
      // case); next_budget_usd is the newly-applied value. Captures
      // the delta for replay + future audit-panel rendering.
      event_type: "canonical_dis_cost_budget_set";
      tenant_id: string;
      tenant_name: string;
      prev_budget_usd: number | null;
      next_budget_usd: number;
    }
  | {
      // Phase 5d.6: a canonical field was soft-deleted from the admin
      // edit page. Classification is breaking by definition — removal
      // of a referenced field is a breaking change in downstream
      // consumers' eyes. Restore via the corresponding restore event.
      event_type: "canonical_schema_field_soft_deleted";
      domain_id: string;
      field_id: string;
      field_name: string;
      classification: "breaking";
    }
  | {
      // Phase 5d.6: a previously soft-deleted field was restored.
      event_type: "canonical_schema_field_restored";
      domain_id: string;
      field_id: string;
      field_name: string;
    };

export type AuditEvent = AuditEventInput & ActorFields;

export function recordAuditEvent(input: AuditEventInput): void {
  const persona = getAuthSnapshot()?.user;
  const event: AuditEvent = {
    ...input,
    user_id: persona?.userId ?? "anonymous",
    user_name: persona?.name ?? "Unknown",
    occurred_at: new Date().toISOString(),
  };
  console.log(`[dis-audit] ${event.event_type}`, event);
  // Fire-and-forget. MSW returns 204; failures are non-blocking for the
  // calling UX. Real backend in 5e will surface failures explicitly.
  void disApiFetch<void>(`/api/v1/dis/audit-events`, {
    method: "POST",
    body: JSON.stringify(event),
  }).catch(() => {
    // Swallow — UX should not break on audit failure in v1.
  });
}
