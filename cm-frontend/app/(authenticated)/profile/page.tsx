import { cookies } from "next/headers";
import { redirect } from "next/navigation";

import { findDevSeedById } from "@/lib/auth/personas";
import { ProfileSecuritySection } from "@/components/profile/ProfileSecuritySection";
import { ProfileNotificationPrefs } from "@/components/profile/ProfileNotificationPrefs";
import { initials, avatarTone } from "@/lib/utils/initials";
import { cn } from "@/lib/utils";

const PERSONA_COOKIE = "__ithina_dev_persona";

// Phase 5f.W.1: ProfilePage is a server component (cookies access),
// so the JWT-decode flow doesn't apply here directly. Dev seed
// display values are read from the catalogue cookie, which gives us
// the same display result as the client-side AuthSnapshot.
// Per-user role display deferred to /api/v1/role-assignments?user_id
// wiring; for now show the userType label (Platform admin / Tenant
// member) per Phase 5f.W.1.
function userTypeLabel(userType: "PLATFORM" | "TENANT"): string {
  return userType === "PLATFORM" ? "Platform admin" : "Tenant member";
}

export default async function ProfilePage() {
  const store = await cookies();
  const personaId = store.get(PERSONA_COOKIE)?.value ?? null;
  const user = personaId ? findDevSeedById(personaId) : undefined;
  if (!user) redirect("/dev/login");

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-8 px-6 py-10">
      <header className="flex flex-col gap-1">
        <h1 className="text-display">Profile</h1>
        <p className="text-sm text-muted-foreground">
          Read-only in v0. Editing lands when Auth0 is wired.
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
                ? "Platform (Ithina)"
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
