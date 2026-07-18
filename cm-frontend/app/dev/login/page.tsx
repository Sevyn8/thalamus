"use client";

import { Suspense, useState } from "react";
import { useRouter } from "next/navigation";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { IthinaLogo } from "@/components/chrome/IthinaLogo";
import { LoginForm } from "@/components/auth/LoginForm";
import { DEV_PERSONA_SEEDS, type DevPersonaSeed } from "@/lib/auth/personas";
import { setCurrentPersona } from "@/lib/auth/getAuthToken";
import { useRuntimeConfig } from "@/lib/config/runtime-config";

// Phase 5d.1: dev-login refactored to two-card layout:
//   - "Production sign-in" (Auth0) — scaffolding for the eventual
//     production auth swap. Button disabled today; tooltip explains.
//   - "Dev login (persona)" — the existing persona-switcher grid,
//     unchanged behavior except the post-pick redirect now lands on
//     /my-ithina instead of /superadmin/dashboard.
//
// Both sections coexist deliberately. When Auth0 ships, the dev card
// stays for local dev / demo workflows and the prod card flips to
// active.

function DevLoginInner() {
  const router = useRouter();
  const [pendingId, setPendingId] = useState<string | null>(null);
  const { config, ready } = useRuntimeConfig();

  // Auth mode is runtime config (from /api/config), not build-inlined.
  // Wait for it before branching so a real (auth0) build never flashes
  // the dev persona switcher.
  if (!ready) {
    return (
      <main className="flex h-screen w-screen items-center justify-center text-sm text-muted-foreground">
        Loading…
      </main>
    );
  }

  const authMode = config?.authMode ?? "stub";

  if (authMode !== "stub") {
    return (
      <main className="mx-auto max-w-2xl p-12">
        <h1 className="text-2xl font-semibold">Dev login disabled</h1>
        <p className="mt-4 text-muted-foreground">
          Auth0 is configured. Use the production login flow at <code>/login</code>.
        </p>
      </main>
    );
  }

  function pick(seed: DevPersonaSeed) {
    setPendingId(seed.id);
    setCurrentPersona(seed.id);
    // Phase 5g.1.3: always land at /my-ithina (launcher-first). The
    // prior `?from` param was deprecated end-to-end — stale deep-links
    // post re-auth are more confusing than helpful.
    router.replace("/my-ithina");
    router.refresh();
  }

  return (
    <main className="mx-auto max-w-3xl p-12">
      <div className="mb-6 flex flex-col gap-3">
        <IthinaLogo size={64} />
      </div>

      <div className="mb-8 rounded-md border border-amber-500/40 bg-amber-500/10 px-4 py-3 text-sm text-amber-200">
        DEV LOGIN: stub auth mode. Personas only available when{" "}
        <code>AUTH_MODE=stub</code>.
      </div>

      <h1 className="text-3xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-2 text-muted-foreground">
        Sign in with your email + password, or pick a persona below to
        continue in dev.
      </p>

      <section className="mt-8">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Production sign-in
        </h2>
        <Card className="mt-3">
          <CardHeader>
            <CardTitle>Sign in to your account</CardTitle>
            <p className="text-sm text-muted-foreground">
              Email + password authentication. The production sign-in
              service is being wired up; if it&apos;s not yet available,
              use the dev login below.
            </p>
          </CardHeader>
          <CardContent>
            <LoginForm />
          </CardContent>
        </Card>
      </section>

      <section className="mt-10">
        <h2 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Dev login (persona)
        </h2>
        <p className="mt-2 text-sm text-muted-foreground">
          Pre-minted JWTs from the runtime <code>DEV_JWT_MAP</code> env var
          authenticate real-backend calls, dispensed by{" "}
          <code>/api/dev-token</code>. Personas without a configured JWT
          cannot complete real-backend calls.
        </p>

        <div className="mt-4 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {DEV_PERSONA_SEEDS.map((p) => (
            <Card
              key={p.id}
              role="button"
              tabIndex={0}
              aria-disabled={pendingId !== null}
              data-pending={pendingId === p.id}
              onClick={() => pendingId === null && pick(p)}
              onKeyDown={(e) => {
                if (pendingId === null && (e.key === "Enter" || e.key === " ")) {
                  e.preventDefault();
                  pick(p);
                }
              }}
              className="cursor-pointer transition-colors hover:bg-accent/40 data-[pending=true]:opacity-70"
            >
              <CardHeader>
                <CardTitle>{p.name}</CardTitle>
                <p className="text-sm text-muted-foreground">{p.email}</p>
              </CardHeader>
              <CardContent className="flex flex-wrap gap-2">
                <Badge variant={p.userType === "PLATFORM" ? "default" : "secondary"}>
                  {p.userType}
                </Badge>
                {p.tenantName ? (
                  <Badge variant="outline" className="ml-auto">
                    {p.tenantName}
                  </Badge>
                ) : null}
                {!p.hasRealJwt ? (
                  <Badge variant="outline" className="border-amber-500/40 text-amber-300">
                    MSW only
                  </Badge>
                ) : null}
              </CardContent>
            </Card>
          ))}
        </div>
      </section>
    </main>
  );
}

export default function DevLoginPage() {
  return (
    <Suspense fallback={null}>
      <DevLoginInner />
    </Suspense>
  );
}
