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
  //
  // THIS ONE IS A DIFFERENT HEDGE FOR A DIFFERENT PATH AND IT STAYS. It has no
  // relationship to dis-ui-ver2 and nothing external depends on it. Two sibling
  // entries for /my-ithina lived here until the launcher rename was finished and
  // were deleted once dis-ui-ver2 shipped an image built against /my-sevyn8;
  // whoever is next removing a redirect should not take this one with them.
  async redirects() {
    return [
      {
        source: "/ithina/:path*",
        destination: "/superadmin/:path*",
        permanent: false,
      },
    ];
  },
};

export default nextConfig;
