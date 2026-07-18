export default async function AcceptInvitePage({
  params,
}: {
  params: Promise<{ token: string }>;
}) {
  const { token } = await params;
  return (
    <main className="mx-auto flex min-h-screen max-w-md flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="text-2xl font-semibold tracking-tight">Accept invitation</h1>
      <p className="text-sm text-muted-foreground">
        Invite acceptance is handled by Auth0 in production. This route is a v0 placeholder.
      </p>
      <code className="rounded bg-muted px-2 py-1 text-xs">token: {token}</code>
    </main>
  );
}
