import type { Metadata } from "next";
import { IBM_Plex_Mono, IBM_Plex_Sans } from "next/font/google";
import "./globals.css";

import { Providers } from "./providers";
import { Toaster } from "@/components/ui/sonner";

// IBM Plex Sans / Mono — the dis-ui-ver2 families, so CM and DIS read as one product.
//
// WEIGHTS MATCH ver2's ACTUAL LOADED SET, not next/font's defaults. ver2 imports
// @fontsource/ibm-plex-sans 400/500/600/700 and ibm-plex-mono 400/500/600
// (dis-ui-ver2/src/main.tsx:8-14). IBM Plex is not a variable font on Google Fonts, so the
// weights must be listed explicitly — omitting them silently ships 400 only and every
// font-weight:500/600 in the app falls back to a synthesised bold.
//
// MECHANISM DIFFERS FROM ver2 BY NECESSITY: ver2 is Vite and imports @fontsource CSS;
// next/font self-hosts, preloads and reserves metrics to avoid CLS, which is the Next-native
// equivalent. Same families, same weights, same latin subset.
const plexSans = IBM_Plex_Sans({
  variable: "--font-plex-sans",
  subsets: ["latin"],
  weight: ["400", "500", "600", "700"],
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  variable: "--font-plex-mono",
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  display: "swap",
});

export const metadata: Metadata = {
  title: "Sevyn8 Superadmin Console",
  description: "Operator surface for the Sevyn8 retail intelligence platform.",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html
      lang="en"
      suppressHydrationWarning
      className={`${plexSans.variable} ${plexMono.variable} h-full antialiased`}
    >
      <body className="min-h-full flex flex-col">
        <Providers>{children}</Providers>
        <Toaster />
      </body>
    </html>
  );
}
