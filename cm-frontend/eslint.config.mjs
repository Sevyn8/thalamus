import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = defineConfig([
  ...nextVitals,
  ...nextTs,
  // Override default ignores of eslint-config-next.
  globalIgnores([
    // Default ignores of eslint-config-next:
    ".next/**",
    "out/**",
    "build/**",
    "next-env.d.ts",
    // Playwright artifacts (Phase 5c.regression). HTML report bundle
    // contains shipped third-party JS that should never be linted.
    "playwright-report/**",
    "test-results/**",
    "playwright/.cache/**",
  ]),
]);

export default eslintConfig;
