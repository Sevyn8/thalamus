// Phase 5c.2c1 hotfix: tiny cron-expression humanizer for display.
// Stream records store schedule as a cron string (technical truth);
// Stream detail page's Schedule tile calls humanizeCron() to render a
// friendlier label. Phase 5e.4e: pre-split Source records also carried
// schedule; that field retired alongside the Source.schedule type
// drop. AddStreamWizard's review step renders raw cron; this helper
// stays for the Stream detail tile + future stream-edit form.
//
// v1 recognizes the patterns currently in MSW fixtures. Falls back to
// the raw cron string for anything unknown — honest behavior; better
// to display the technical truth than guess wrong. Real backend will
// likely emit pre-humanized labels as a separate field, or the
// frontend can adopt a proper cron-parser library if the demo
// surfaces grow.

const DAYS = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"];

export function humanizeCron(cron: string | null | undefined): string {
  if (!cron) return "—";
  const trimmed = cron.trim();

  // Every N minutes: */N * * * *
  const everyN = /^\*\/(\d+)\s+\*\s+\*\s+\*\s+\*$/.exec(trimmed);
  if (everyN) {
    const n = Number(everyN[1]);
    return `Every ${n} minute${n === 1 ? "" : "s"}`;
  }

  // Every hour: 0 * * * *
  if (trimmed === "0 * * * *") return "Every hour";

  // Daily at HH:00 UTC: 0 H * * *
  const dailyAt = /^0\s+(\d{1,2})\s+\*\s+\*\s+\*$/.exec(trimmed);
  if (dailyAt) {
    const h = Number(dailyAt[1]);
    return `Daily at ${String(h).padStart(2, "0")}:00 UTC`;
  }

  // Weekly on day at HH:00 UTC: 0 H * * D (D=0..6, 0=Sunday)
  const weeklyAt = /^0\s+(\d{1,2})\s+\*\s+\*\s+(\d)$/.exec(trimmed);
  if (weeklyAt) {
    const h = Number(weeklyAt[1]);
    const d = Number(weeklyAt[2]);
    const day = DAYS[d] ?? `day ${d}`;
    return `Weekly on ${day} ${String(h).padStart(2, "0")}:00 UTC`;
  }

  // Unknown pattern → fall back to raw cron string. Honest about what
  // the schedule actually is; lets demo audiences recognize their own
  // custom expressions.
  return trimmed;
}
