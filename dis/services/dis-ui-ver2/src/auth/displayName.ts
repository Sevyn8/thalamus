// Display-name derivation for the topbar.
//
// DELIBERATELY MIRRORED, LINE FOR LINE, from
// cm-frontend/lib/auth/persona-from-claims.ts's deriveNameFromEmail. Keep the two
// together: a tenant admin moves between Customer Master and DIS through the launcher,
// and two different renderings of the same person read as two products rather than one.
// If CM's derivation changes, change this with it (and vice versa) — do not let them
// drift, and do not invent a second transform here.
//
// WHY A DERIVATION EXISTS AT ALL. The shared cortex-cm-claims Auth0 Action stamps
// user_id / user_type / tenant_id / email and NO name claim, because Customer Master
// creates users via the Management API with an email and app_metadata only. So there is
// no name to show, in either product, until someone sets one upstream. The real fix is
// in CM's user creation, not here.
//
// Known consequences, accepted:
//   - dotted locals read a little oddly: a.kowalski@zabka.pl -> "A.kowalski", because
//     only the FIRST character is upper-cased (no per-segment title-casing, no splitting
//     on dots, nothing stripped).
//   - the domain is dropped, so amit@sevyn8.com and amit@othertenant.com both render
//     "Amit". Inherent to any local-part derivation.
export function deriveNameFromEmail(email: string): string {
  const local = email.split('@')[0] ?? ''
  if (local.length === 0) return 'User'
  return local.charAt(0).toUpperCase() + local.slice(1)
}

// The topbar's display string: a real name when one exists, otherwise derived from the
// email, otherwise nothing. Returns null rather than a placeholder so the caller can
// omit the element entirely instead of rendering "Unknown user".
export function displayNameFor(profile: { name: string | null; email: string | null }): string | null {
  if (profile.name !== null && profile.name.length > 0) return profile.name
  if (profile.email !== null && profile.email.length > 0) return deriveNameFromEmail(profile.email)
  return null
}
