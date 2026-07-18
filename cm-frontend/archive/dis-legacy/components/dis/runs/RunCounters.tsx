import type { Run } from "@/types/dis";

// Phase 5c.3b: row-counter cards. Renders nothing for runs without
// counters (QUEUED, RUNNING) since the numbers haven't been
// determined yet — the parent run-detail page can choose whether to
// hide the section.

type Props = {
  run: Run;
};

export function RunCounters({ run }: Props) {
  if (run.rows_ingested === null) return null;
  return (
    <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
      <Counter
        label="Rows ingested"
        value={run.rows_ingested.toLocaleString()}
        emphasis="primary"
      />
      <Counter
        label="Rows failed"
        value={(run.rows_failed ?? 0).toLocaleString()}
        emphasis={(run.rows_failed ?? 0) > 0 ? "danger" : "muted"}
      />
      <Counter
        label="Rows skipped"
        value={(run.rows_skipped ?? 0).toLocaleString()}
        emphasis={(run.rows_skipped ?? 0) > 0 ? "warning" : "muted"}
      />
    </div>
  );
}

function Counter({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis: "primary" | "danger" | "warning" | "muted";
}) {
  const valueClass =
    emphasis === "danger"
      ? "text-danger"
      : emphasis === "warning"
        ? "text-warning"
        : emphasis === "muted"
          ? "text-muted-foreground"
          : "text-foreground";
  return (
    <div className="flex flex-col gap-1 rounded-md border border-border bg-card/30 p-4">
      <span className="text-label text-muted-foreground">{label}</span>
      <span className={`text-display font-semibold ${valueClass}`}>{value}</span>
    </div>
  );
}
