"use client";

import type { ConnectionConfig, SystemKind } from "@/types/dis";

import { CsvScheduledForm } from "./config-forms/CsvScheduledForm";
import { FtpForm } from "./config-forms/FtpForm";
import { NamedPosOAuthForm } from "./config-forms/NamedPosOAuthForm";
import { PosApiGenericForm } from "./config-forms/PosApiGenericForm";
import { RestApiGenericForm } from "./config-forms/RestApiGenericForm";
import { ShopifyPosForm } from "./config-forms/ShopifyPosForm";

type Props = {
  type: SystemKind;
  value: Partial<ConnectionConfig>;
  onChange: (next: Partial<ConnectionConfig>, valid: boolean) => void;
};

// Phase 5c.2b2 step 3: per-type config switchboard. Routes to the
// matching form component based on selected source type. Form owns
// its own validation rules (per A6); valid: boolean propagates up
// to the wizard's canAdvance gate.

export function StepConfig({ type, value, onChange }: Props) {
  switch (type) {
    case "SQUARE":
    case "LIGHTSPEED":
    case "TOAST":
    case "CLOVER":
      return <NamedPosOAuthForm variant={type} value={value} onChange={onChange} />;
    case "SHOPIFY_POS":
      return <ShopifyPosForm value={value} onChange={onChange} />;
    case "POS_API_GENERIC":
      return <PosApiGenericForm value={value} onChange={onChange} />;
    case "CSV_SCHEDULED":
      return <CsvScheduledForm value={value} onChange={onChange} />;
    case "FTP":
      return <FtpForm value={value} onChange={onChange} />;
    case "REST_API_GENERIC":
      return <RestApiGenericForm value={value} onChange={onChange} />;
    default: {
      // Exhaustiveness — TS errors here if SystemKind gains a variant
      // without a matching case.
      const _exhaustive: never = type;
      void _exhaustive;
      return null;
    }
  }
}
