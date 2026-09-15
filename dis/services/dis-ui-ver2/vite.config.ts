/// <reference types="vitest/config" />
import { fileURLToPath } from 'node:url'

import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// P1-SEC-001. '@devAuthSeam' is resolved HERE, at build time, to one of two files with the
// same interface (src/auth/seam/). That resolution is the security boundary:
//
//   deployable production build -> devAuthSeam.prod.tsx -> imports nothing from src/auth/dev
//   dev server / vitest         -> devAuthSeam.dev.tsx  -> the persona picker and stub signer
//
// A RUNTIME check could not do this. `if (import.meta.env.PROD) throw` leaves the fixture
// provider, the persona identities and the published HS256 constant in the emitted chunk,
// where anyone can read them out of the served JavaScript and mint a token themselves. The
// deployed v18 bundle contained all three. Removing the import path is what removes them.
//
// scripts/assert-no-dev-auth.mjs re-checks the built bytes afterwards, because this comment
// is a claim about a graph and that script is a measurement of what shipped.
export default defineConfig(({ command }) => {
  // vitest runs through this config too and needs the fixture modules for DevLogin /
  // verifyToken coverage, so it is explicitly on the dev side of the seam.
  const isProductionBuild = command === 'build' && process.env.VITEST === undefined
  const requestedMode = process.env.VITE_DIS_UI_SERVER_MODE

  // FAIL CLOSED, AND ONLY ON AN EXPLICIT REQUEST. A deployable build that was actually asked
  // for fixture mode is a mistake worth stopping: the alternative is shipping a public artifact
  // whose auth is a persona dropdown. A MISSING or misspelled value is not an error here - it
  // resolves to the production seam, so the artifact is real-only by construction rather than
  // by the operator having spelled a variable correctly. See App.tsx's `?? <RealModeApp />`.
  if (isProductionBuild && requestedMode === 'fixture') {
    throw new Error(
      'VITE_DIS_UI_SERVER_MODE=fixture was requested for a production build. Fixture mode ' +
        'ships the persona picker and the published HS256 stub constant, which dis-ui-server ' +
        'accepts in STUB mode, so the artifact would carry a forgeable login. Use `vite dev` ' +
        'for fixture work, or build with VITE_DIS_UI_SERVER_MODE=real.',
    )
  }

  const devAuthSeam = isProductionBuild
    ? './src/auth/seam/devAuthSeam.prod.tsx'
    : './src/auth/seam/devAuthSeam.dev.tsx'

  return {
    plugins: [react(), tailwindcss()],
    server: {
      proxy: {
        '/api': {
          target: process.env.VITE_DEV_PROXY_TARGET || 'http://localhost:8080',
          changeOrigin: true,
        },
      },
    },
    resolve: {
      alias: {
        '@devAuthSeam': fileURLToPath(new URL(devAuthSeam, import.meta.url)),
        '@': fileURLToPath(new URL('./src', import.meta.url)),
      },
    },
    test: {
      globals: true,
      environment: 'jsdom',
      setupFiles: './src/test/setup.ts',
    },
  }
})
