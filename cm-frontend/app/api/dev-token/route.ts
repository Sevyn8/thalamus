import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { isPersonaId } from "@/lib/auth/personas";

// Guarded dev-token dispenser. Reads DEV_JWT_MAP (JSON object mapping a
// persona id to its pre-minted JWT) from server env at request time and
// returns the token for ?persona=<id>. Adding a token for an existing
// persona is config-only: edit DEV_JWT_MAP, bounce the revision.
//
// GUARD: this serves ONLY in stub/dev auth modes. A real (auth0) build
// returns 404, so a token-dispensing route never exists in production.
//
// force-dynamic keeps the env reads at request time (see /api/config).
export const dynamic = "force-dynamic";

function devAuthEnabled(): boolean {
  const mode = process.env.AUTH_MODE ?? "stub";
  return mode === "stub" || mode === "dev";
}

export function GET(request: NextRequest) {
  if (!devAuthEnabled()) {
    return new NextResponse("Not found", { status: 404 });
  }

  const persona = request.nextUrl.searchParams.get("persona");
  if (!isPersonaId(persona)) {
    return NextResponse.json({ error: "unknown persona" }, { status: 400 });
  }

  let token: string | null = null;
  const raw = process.env.DEV_JWT_MAP;
  if (raw) {
    try {
      const parsed = JSON.parse(raw) as unknown;
      if (parsed && typeof parsed === "object") {
        const value = (parsed as Record<string, unknown>)[persona];
        if (typeof value === "string" && value) token = value;
      }
    } catch {
      // Malformed DEV_JWT_MAP: treat as no token configured.
    }
  }

  return NextResponse.json({ token });
}
