import type { ConnectionConfig, SystemKind } from "@/types/dis";

// Phase 5c.2c1: read-only Config tab on /dis/sources/[id]. Mirrors
// StepConfig switchboard from 5c.2b2 but renders fields as labelled
// values instead of inputs. Same 9-variant exhaustiveness via
// assertNever — adding a new SystemKind without a Display case fails
// the build.
//
// Per Sd: credentials_ref always renders as `••••••••` regardless of
// persona. No View raw affordance — credentials are a different
// permission family from dis.pii.view; not in v1 scope.

type Props = {
  type: SystemKind;
  config: Record<string, unknown>;
};

const MASKED_CREDS = "••••••••";

function ItemRow({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-0.5">
      <span className="text-label text-muted-foreground">{label}</span>
      <span className="text-sm break-all">{value}</span>
    </div>
  );
}

function Grid({ children }: { children: React.ReactNode }) {
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">{children}</div>
  );
}

function ValueOrDash({ value }: { value: string | undefined | null }) {
  if (!value) return <span className="text-muted-foreground">—</span>;
  return <>{value}</>;
}

export function SourceConfigDisplay({ type, config }: Props) {
  const c = config as Record<string, unknown> &
    Partial<Extract<ConnectionConfig, { type: typeof type }>>;

  switch (type) {
    case "SQUARE":
      return (
        <Grid>
          <ItemRow label="Merchant ID" value={<ValueOrDash value={c.merchant_id as string | undefined} />} />
          <ItemRow label="Location ID" value={<ValueOrDash value={c.location_id as string | undefined} />} />
          <ItemRow label="Environment" value={<ValueOrDash value={c.environment as string | undefined} />} />
        </Grid>
      );
    case "LIGHTSPEED":
      return (
        <Grid>
          <ItemRow label="Account ID" value={<ValueOrDash value={c.account_id as string | undefined} />} />
          <ItemRow label="Environment" value={<ValueOrDash value={c.environment as string | undefined} />} />
        </Grid>
      );
    case "SHOPIFY_POS":
      return (
        <Grid>
          <ItemRow label="Shop domain" value={<ValueOrDash value={c.shop_domain as string | undefined} />} />
        </Grid>
      );
    case "TOAST":
      return (
        <Grid>
          <ItemRow label="Restaurant GUID" value={<ValueOrDash value={c.restaurant_guid as string | undefined} />} />
          <ItemRow label="Environment" value={<ValueOrDash value={c.environment as string | undefined} />} />
        </Grid>
      );
    case "CLOVER":
      return (
        <Grid>
          <ItemRow label="Merchant ID" value={<ValueOrDash value={c.merchant_id as string | undefined} />} />
          <ItemRow label="Environment" value={<ValueOrDash value={c.environment as string | undefined} />} />
        </Grid>
      );
    case "POS_API_GENERIC":
      return (
        <Grid>
          <ItemRow label="Endpoint URL" value={<ValueOrDash value={c.endpoint_url as string | undefined} />} />
          <ItemRow label="Auth type" value={<ValueOrDash value={c.auth_type as string | undefined} />} />
          <ItemRow label="Credentials" value={c.credentials_ref ? MASKED_CREDS : <ValueOrDash value={null} />} />
        </Grid>
      );
    case "CSV_SCHEDULED":
      return (
        <Grid>
          <ItemRow label="File pattern" value={<ValueOrDash value={c.file_pattern as string | undefined} />} />
          <ItemRow label="Source URL or FTP" value={<ValueOrDash value={c.source_url_or_ftp as string | undefined} />} />
        </Grid>
      );
    case "FTP":
      return (
        <Grid>
          <ItemRow label="Host" value={<ValueOrDash value={c.host as string | undefined} />} />
          <ItemRow label="Port" value={<ValueOrDash value={c.port?.toString()} />} />
          <ItemRow label="Path" value={<ValueOrDash value={c.path as string | undefined} />} />
          <ItemRow label="Username" value={<ValueOrDash value={c.username as string | undefined} />} />
          <ItemRow label="Credentials" value={c.credentials_ref ? MASKED_CREDS : <ValueOrDash value={null} />} />
        </Grid>
      );
    case "REST_API_GENERIC": {
      const headers = (c.headers as Record<string, string> | undefined) ?? {};
      const headerKeys = Object.keys(headers);
      return (
        <div className="flex flex-col gap-3">
          <Grid>
            <ItemRow label="Endpoint URL" value={<ValueOrDash value={c.endpoint_url as string | undefined} />} />
            <ItemRow label="Auth type" value={<ValueOrDash value={c.auth_type as string | undefined} />} />
            <ItemRow label="Credentials" value={c.credentials_ref ? MASKED_CREDS : <ValueOrDash value={null} />} />
          </Grid>
          <ItemRow
            label="Custom headers"
            value={
              headerKeys.length > 0 ? (
                <code className="block rounded-md border border-border bg-card/30 px-2 py-1 font-mono text-xs">
                  {JSON.stringify(headers, null, 2)}
                </code>
              ) : (
                <span className="text-muted-foreground">None</span>
              )
            }
          />
        </div>
      );
    }
    default: {
      const _exhaustive: never = type;
      void _exhaustive;
      return null;
    }
  }
}
