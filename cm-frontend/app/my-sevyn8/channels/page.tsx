"use client";

import Link from "next/link";
import { ArrowLeft } from "lucide-react";

import { Skeleton } from "@/components/shared/Skeleton";
import { ErrorInline } from "@/components/shared/ErrorInline";
import { ChannelConnectionsPane } from "@/components/channels/ChannelConnectionsPane";
import { ChannelCredentialForm } from "@/components/channels/ChannelCredentialForm";
import { useAuthSnapshot } from "@/lib/auth/auth-cache";
import { hasPermission } from "@/lib/auth/permissions-check";
import { useMyChannels } from "@/lib/hooks/use-channels";
import { ApiError } from "@/lib/api/client";

// A tenant administrator configuring their OWN sending channel.
//
// NO [tenantId] SEGMENT, and that is a decision rather than an omission. The
// tenant is in the token and RLS scopes every row the backend returns. A path
// segment would create a token-versus-path mismatch case that then has to be
// quarantined; adding the trap and guarding it is worse than not adding it.
//
// =========================================================================
// THE GUARD IS TWO CONDITIONS AND THE SECOND ONE IS NOT DECORATION
// =========================================================================
// userType === "TENANT" is required IN ADDITION to the permission, because of
// a specific shape on the backend: GET /channels carries no audience pin (PUT
// pins TENANT and GET /channels/platform pins PLATFORM, but the tenant read
// does not), its repository method has no WHERE clause and relies entirely on
// RLS, and the PLATFORM branch of that policy lives in USING. So a PLATFORM
// caller reaching it gets EVERY tenant's rows, which this page would then
// render under the heading "your channels". The scope cascade makes that
// reachable: a GLOBAL grant satisfies a TENANT check server-side.
//
// hasPermission does NOT cascade (lib/auth/permissions-check.ts matches the
// scope exactly), so the permission check alone happens to exclude SUPER_ADMIN
// today. That is a coincidence of two different rules agreeing, not a guarantee,
// and it would stop being true the moment anyone is granted CHANNELS.VIEW at
// TENANT scope on a PLATFORM role. The userType check is what makes it hold.
//
// The gate is still the server's. This is a UX decision made on cached data.

function ChannelsUnavailable() {
  // WHAT A TENANT SEES WHEN THE ADMIN MODULE IS OFF. has_permission's TENANT
  // path joins tenant_module_access on status='ENABLED', so disabling the ADMIN
  // module makes every ADMIN.* grant evaluate false at once and this surface
  // would otherwise simply vanish with no explanation anywhere.
  //
  // The copy names BOTH possible causes and commits to neither, because the
  // client genuinely cannot tell them apart: a missing grant and a disabled
  // module produce an identical absence in /me/permissions.
  return (
    <div className="mx-auto max-w-2xl px-6 py-16">
      <h1 className="text-display">Sending channels</h1>
      <p className="mt-4 text-body text-muted-foreground">
        This surface is not available for your account. Sending channels are part
        of the Admin module, so either that module is not enabled for your
        organisation or your role does not carry permission to configure
        channels. Sevyn8 support can tell you which.
      </p>
      <Link
        href="/my-sevyn8"
        className="mt-8 inline-flex items-center gap-2 text-sm text-primary hover:underline"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to My Sevyn8
      </Link>
    </div>
  );
}

export default function TenantChannelsPage() {
  const snapshot = useAuthSnapshot();

  const isTenant = snapshot?.user?.userType === "TENANT";
  const canView =
    isTenant && hasPermission(snapshot, "ADMIN", "CHANNELS", "VIEW", "TENANT");
  const canConfigure =
    isTenant &&
    hasPermission(snapshot, "ADMIN", "CHANNELS", "CONFIGURE", "TENANT");

  // Fire no request for a caller we will not render to. See the guard note
  // above: for a PLATFORM caller this endpoint answers with the whole fleet.
  const channels = useMyChannels({ enabled: canView });

  // Boot: the snapshot is null until AuthBoundary resolves /me/permissions, and
  // hasPermission fails closed on null. Showing the unavailable copy during
  // boot would accuse a legitimate tenant of lacking access, so wait first.
  if (!snapshot) {
    return (
      <div className="mx-auto max-w-4xl px-6 py-10">
        <Skeleton variant="card" className="h-40" />
      </div>
    );
  }

  if (!canView) return <ChannelsUnavailable />;

  // A 404 here is the expected shape while the channels routes are absent from
  // the deployed cm-backend image, and it is not the tenant's problem to solve.
  // Saying "not yet available" is the true weaker statement; a generic failure
  // would read as though their configuration broke something.
  const notDeployed =
    channels.error instanceof ApiError && channels.error.status === 404;

  return (
    <div className="mx-auto flex max-w-4xl flex-col gap-8 px-6 py-10">
      <div className="flex flex-col gap-2">
        <Link
          href="/my-sevyn8"
          className="inline-flex w-fit items-center gap-2 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" />
          My Sevyn8
        </Link>
        <h1 className="text-display">Sending channels</h1>
        <p className="text-body text-muted-foreground">
          Your organisation is the sender. You enter your own provider
          credential; Sevyn8 stores it and can never read it back.
        </p>
      </div>

      {/* NOTHING SENDS, SAID ON THE PAGE. There is no adapter and no template
          registry, and the database CHECK allows a connection to reach nothing
          past "pending". A page that quietly implied otherwise would be worse
          than one that does not exist. */}
      <div className="rounded-md border border-border bg-surface p-4 text-sm">
        <p className="text-body-strong">Nothing is sent yet.</p>
        <p className="mt-1 text-muted-foreground">
          Saving a channel stores your credential and records the connection. It
          does not send anything and does not schedule anything: the part of
          Sevyn8 that would deliver a message over this channel has not been
          built. A saved channel stays in the state{" "}
          <span className="font-mono">pending</span>, which is the only state it
          can currently reach.
        </p>
      </div>

      <section className="flex flex-col gap-3">
        <h2 className="text-heading">Current connections</h2>
        {channels.isLoading ? (
          <Skeleton variant="card" className="h-32" />
        ) : notDeployed ? (
          <ErrorInline
            title="Not available yet"
            message="This surface is deployed ahead of the service that answers it. Nothing you have configured is affected. Try again after the next Sevyn8 release."
          />
        ) : channels.error ? (
          <ErrorInline
            message="Could not load your channel connections."
            onRetry={() => channels.refetch()}
          />
        ) : (
          <ChannelConnectionsPane connections={channels.data?.items ?? []} />
        )}
      </section>

      {/* The form renders only for a caller who can actually write. Rendering a
          disabled save button for a read-only role (COMPLIANCE_OFFICER holds
          CHANNELS.VIEW.TENANT and not CONFIGURE.TENANT) would be a dead control:
          a form that cannot write. */}
      {canConfigure ? (
        <section className="flex flex-col gap-3">
          <h2 className="text-heading">Configure a channel</h2>
          <ChannelCredentialForm />
        </section>
      ) : (
        <p className="text-caption text-muted-foreground">
          You can see your organisation&apos;s channel connections. Configuring one
          needs a role that carries permission to change channels.
        </p>
      )}
    </div>
  );
}
