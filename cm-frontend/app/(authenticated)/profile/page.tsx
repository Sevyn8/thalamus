import { redirect } from "next/navigation";

import { auth0 } from "@/lib/auth0";
import { claimsFromSessionUser } from "@/lib/auth/jwt-decode";
import { buildPersonaFromClaims } from "@/lib/auth/persona-from-claims";
import { ProfileSecuritySection } from "@/components/profile/ProfileSecuritySection";
import { ProfileNotificationPrefs } from "@/components/profile/ProfileNotificationPrefs";
import { initials, avatarTone } from "@/lib/utils/initials";
import { cn } from "@/lib/utils";

// ProfilePage is a server component; identity comes from the Auth0 session
// (namespaced https://sevyn8.com/* claims), not a client-side decode. Per-user
// role display is deferred to /api/v1/role-assignments; for now show the
// userType label.
function userTypeLabel(userType: "PLATFORM" | "TENANT"): string {
  return userType === "PLATFORM" ? "Platform admin" : "Tenant member";
}

export default async function ProfilePage() {
  const session = await auth0.getSession();
  const claims = claimsFromSessionUser(
    session?.user as Record<string, unknown> | null | undefined,
  );
  if (!claims) redirect("/auth/login");
  const user = buildPersonaFromClaims(claims);

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-8 px-6 py-10">
      <header className="flex flex-col gap-1">
        <h1 className="text-display">Profile</h1>
        <p className="text-sm text-muted-foreground">
          Read-only in v0. Editing lands later.
        </p>
      </header>

      <section className="flex flex-col gap-3 rounded-md border border-border bg-card/30 p-6">
        <h2 className="text-label text-muted-foreground">
          Account
        </h2>
        <div className="flex items-center gap-4">
          <span
            className={cn(
              "flex h-16 w-16 shrink-0 items-center justify-center rounded-md text-heading",
              avatarTone(user.name),
            )}
            aria-hidden="true"
          >
            {initials(user.name)}
          </span>
          <div className="flex min-w-0 flex-col">
            <span className="text-lg font-medium">{user.name}</span>
            <span className="text-sm text-muted-foreground">{user.email}</span>
            <span className="mt-1 text-xs text-muted-foreground">
              {userTypeLabel(user.userType)} ·{" "}
              {user.userType === "PLATFORM"
                ? "Platform (Sevyn8)"
                : user.tenantName ?? "—"}
            </span>
          </div>
        </div>
      </section>

      <ProfileSecuritySection />

      <ProfileNotificationPrefs />
    </main>
  );
}
