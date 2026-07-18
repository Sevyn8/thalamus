export function initials(name: string): string {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase() ?? "")
    .join("");
}

const PALETTE = [
  "bg-blue-500/20 text-blue-200",
  "bg-violet-500/20 text-violet-200",
  "bg-teal-500/20 text-teal-200",
  "bg-emerald-500/20 text-emerald-200",
  "bg-amber-500/20 text-amber-200",
  "bg-fuchsia-500/20 text-fuchsia-200",
  "bg-rose-500/20 text-rose-200",
  "bg-cyan-500/20 text-cyan-200",
];

export function avatarTone(seed: string): string {
  let hash = 0;
  for (let i = 0; i < seed.length; i++) {
    hash = (hash * 31 + seed.charCodeAt(i)) >>> 0;
  }
  const tone = PALETTE[hash % PALETTE.length];
  return tone ?? PALETTE[0]!;
}
