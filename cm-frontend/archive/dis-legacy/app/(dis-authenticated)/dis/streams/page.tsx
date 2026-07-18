import { permanentRedirect } from "next/navigation";

// Phase 5e.9: /dis/streams retired in favor of the unified
// /dis/sources page (Sources & streams). Permanent redirect preserves
// bookmarks pointing here. The standalone Streams fleet view that
// shipped in 5e.4b was visually redundant against /dis/sources in
// MSW-mode demos (1:1 source/stream majority); 5e.8 enriched the
// fixture density and 5e.9 consolidated the surface.

export default function Page() {
  permanentRedirect("/dis/sources");
}
