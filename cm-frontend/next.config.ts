import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  output: "standalone",

  // Phase 5a.3 future-proofing hedge. /ithina/* is not a real namespace
  // in this app — the Ithina product lives at /superadmin/* — but the
  // surface map's product-switcher framing makes /ithina/* a plausible
  // user guess. Redirect to the canonical /superadmin/* path so
  // hand-typed URLs and any external link that anticipates the
  // alternate naming still lands. permanent: false (307) because this
  // is a hedge, not a settled URL design choice; if /superadmin
  // officially renames to /ithina later, the destination flips and
  // this becomes permanent: true (308).
  // The launcher moved from /my-ithina to /my-sevyn8. Ithina is a CLIENT, and
  // their name was on the breadcrumb of every Sevyn8 tenant's own settings page.
  // The rest of the product already said "My Sevyn8", so this closed a gap
  // rather than opening one.
  //
  // THIS REDIRECT IS NOT FOR BOOKMARKS. dis-ui-ver2 renders the only upward link
  // in its chrome from VITE_CM_LAUNCHER_URL, and Vite inlines import.meta.env at
  // BUILD time, so the old path is baked into the image that is deployed right
  // now. Editing dis/terraform/docker/cloudbuild-dis-ui-ver2.yaml changes nothing
  // until that image is rebuilt. Until then this redirect is the only thing
  // keeping DIS users from a dead end.
  //
  // permanent: false (307), deliberately. Its job is transitional and its
  // consumer is a server-side baked string that does not cache; a 308 would
  // instead persist in browsers for a naming decision that has already been
  // reversed once. DELETE THIS ENTRY once dis-ui-ver2 ships an image built
  // against /my-sevyn8. Both forms are listed rather than relying on :path*
  // also matching the bare path: the launcher's own URL should not depend on
  // anyone's reading of a matcher's zero-or-more semantics.
  async redirects() {
    return [
      {
        source: "/ithina/:path*",
        destination: "/superadmin/:path*",
        permanent: false,
      },
      {
        source: "/my-ithina",
        destination: "/my-sevyn8",
        permanent: false,
      },
      {
        source: "/my-ithina/:path*",
        destination: "/my-sevyn8/:path*",
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
