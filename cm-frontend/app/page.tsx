import { redirect } from "next/navigation";

import { auth0 } from "@/lib/auth0";

// Root entry. Authenticated -> the launcher; otherwise -> Auth0 login. The
// middleware also gates protected routes, but this gives "/" a definite
// destination based on the session.
export default async function RootPage() {
  const session = await auth0.getSession();
  redirect(session ? "/my-ithina" : "/auth/login");
}
