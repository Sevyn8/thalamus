import type { Run } from "@/types/dis";

// Phase 5c.3b: stub log viewer for run detail. Generates 6-10
// deterministic-by-run.id log lines so refresh shows the same content
// (avoids the "ooh look this changed each time" demo distraction).
// Live log streaming lands in Phase 5d alongside cancellation.

type Level = "INFO" | "WARN" | "ERROR";

type LogLine = {
  ts_offset_ms: number;
  level: Level;
  message: string;
};

const POOL_INFO = [
  "Worker accepted job, leasing connection",
  "Connected to source",
  "Fetched batch %d",
  "Wrote batch %d to staging",
  "Schema validation passed",
  "Heartbeat sent",
  "Released lease",
];

const POOL_WARN = [
  "Retry %d on transient network blip",
  "Skipped %d rows with malformed timestamps",
  "Rate limit headroom below 20%",
];

const POOL_ERROR = [
  "Source returned %s",
  "Aborted after maximum retries",
];

// Tiny deterministic PRNG — mulberry32 seeded from a hash of the
// run id. Same run id always produces the same line set + ordering.
function hash(str: string): number {
  let h = 2166136261;
  for (let i = 0; i < str.length; i++) {
    h ^= str.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return h >>> 0;
}

function makePrng(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s + 0x6d2b79f5) >>> 0;
    let t = s;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

function generateLines(run: Run): LogLine[] {
  const rng = makePrng(hash(run.id));
  const count = 6 + Math.floor(rng() * 5); // 6-10 lines
  const lines: LogLine[] = [];
  let cursor = 0;
  for (let i = 0; i < count; i++) {
    cursor += Math.floor(rng() * 4000) + 200; // 200-4200ms gaps
    const isLast = i === count - 1;
    let level: Level = "INFO";
    let pool = POOL_INFO;
    // Sprinkle a WARN or two; on FAILED runs, end with an ERROR.
    if (isLast && run.status === "FAILED") {
      level = "ERROR";
      pool = POOL_ERROR;
    } else if (rng() < 0.18) {
      level = "WARN";
      pool = POOL_WARN;
    }
    let msg = pool[Math.floor(rng() * pool.length)] ?? "Unknown";
    msg = msg.replace("%d", String(Math.floor(rng() * 8) + 1));
    msg = msg.replace("%s", run.error_code ?? "ERROR");
    lines.push({ ts_offset_ms: cursor, level, message: msg });
  }
  return lines;
}

function formatTimestamp(startedAt: string | null, offsetMs: number): string {
  const base = startedAt ? new Date(startedAt).getTime() : Date.now();
  const t = new Date(base + offsetMs);
  return t.toISOString().replace("T", " ").replace("Z", "Z");
}

const LEVEL_CLASS: Record<Level, string> = {
  INFO: "text-muted-foreground",
  WARN: "text-warning",
  ERROR: "text-danger",
};

export function RunLogsStub({ run }: { run: Run }) {
  // QUEUED runs have no started_at and no log activity yet — show a
  // brief placeholder rather than synthesized lines.
  if (run.status === "QUEUED") {
    return (
      <div className="rounded-md border border-border bg-card/30 p-5 text-caption text-muted-foreground">
        Run is queued; no log output yet.
      </div>
    );
  }
  const lines = generateLines(run);
  return (
    <div className="flex flex-col gap-2 rounded-md border border-border bg-card/30 p-4">
      <div className="flex items-center justify-between">
        <h3 className="text-label text-muted-foreground">Logs</h3>
        <span className="text-micro text-muted-foreground">
          v1 stub · live streaming in Phase 5d
        </span>
      </div>
      <pre className="overflow-x-auto rounded-md bg-background/60 p-3 text-xs leading-relaxed">
        {lines.map((l, i) => (
          <div key={i} className="font-mono">
            <span className="text-muted-foreground">
              {formatTimestamp(run.started_at, l.ts_offset_ms)}
            </span>{" "}
            <span className={LEVEL_CLASS[l.level]}>[{l.level}]</span>{" "}
            <span>{l.message}</span>
          </div>
        ))}
      </pre>
    </div>
  );
}
