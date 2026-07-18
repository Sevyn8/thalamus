import { Chip } from "@/components/shared/Chips";

// Phase 5e.6: SUPER-only chip. NORMAL templates render no kind chip
// (the default state — keeps fleet table tidy when most templates are
// single-domain). SUPER renders a violet "Super" badge to signal the
// multi-domain combine surface introduced in 5e.6.

export function TemplateKindChip() {
  return <Chip tone="violet">Super</Chip>;
}
