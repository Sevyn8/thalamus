import { cookies } from "next/headers";
import { redirect } from "next/navigation";

const PERSONA_COOKIE = "__ithina_dev_persona";

export default async function RootPage() {
  // Runtime, non-prefixed env. Read server-side at request time so the
  // value is not frozen into the build.
  const authMode = process.env.AUTH_MODE === "auth0" ? "auth0" : "stub";
  const store = await cookies();
  const hasPersona = !!store.get(PERSONA_COOKIE)?.value;
  if (hasPersona) {
    redirect("/my-ithina");
  }
  redirect(authMode === "stub" ? "/dev/login" : "/login");
}
