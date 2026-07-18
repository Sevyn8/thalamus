"use client";

import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";

export function ImpersonationBanner() {
  const search = useSearchParams();
  const router = useRouter();
  const pathname = usePathname() ?? "/";
  const snapshot = useAuthSnapshot();

  if (search.get("impersonating") !== "true") return null;

  const targetName = search.get("user") ?? "a tenant user";
  const targetRole = search.get("role") ?? "Owner";
  const ticket = search.get("ticket") ?? "TKT-0000";
  const remaining = search.get("remaining") ?? "27 min remaining";
  const actor = snapshot?.user.name ?? "Support Admin";

  function endSession() {
    const params = new URLSearchParams(search.toString());
    params.delete("impersonating");
    params.delete("user");
    params.delete("role");
    params.delete("ticket");
    params.delete("remaining");
    const next = params.toString();
    router.replace(next ? `${pathname}?${next}` : pathname);
  }

  return (
    <div className="sticky top-0 z-30 flex items-center justify-between gap-4 bg-orange-500 px-6 py-2 text-sm text-orange-50 shadow">
      <span>
        <span className="font-medium">{actor}</span> is impersonating{" "}
        <span className="font-medium">{targetName}</span> ({targetRole}) for ticket {ticket}.{" "}
        {remaining}.
      </span>
      <button
        type="button"
        onClick={endSession}
        className="rounded-md border border-orange-50/50 px-3 py-1 text-xs font-medium hover:bg-orange-50/10"
      >
        End session
      </button>
    </div>
  );
}
