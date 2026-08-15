import { defineConfig, globalIgnores } from "eslint/config";
import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

// THE GATE IS TIGHTENED IN package.json, NOT HERE, because the script is where the exit
// code is decided: `eslint --max-warnings 0 --report-unused-disable-directives`. Both flags
// earn their place and it was checked rather than assumed: without them an unused
// eslint-disable directive is reported as a WARNING and eslint exits 0, so suppressions that
// have stopped suppressing anything accumulate into a second soft baseline underneath the
// first. With them the same directive is an error and the run fails.
//
// ARCHIVED DEAD CODE IS ON THIS GATE. archive/** is linted and is clean today, so
// --max-warnings 0 puts code nobody maintains on the critical path of every lint run. If it
// ever warns, the fix is to ignore archive/** here, not to edit dead code to satisfy a rule
// it was written before. Not ignored now, because an ignore added ahead of a problem is an
// ignore nobody can justify later.
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
    // THE THREE PLAYWRIGHT IGNORES THAT WERE HERE ARE GONE. There is no Playwright
    // in this package: not in package.json, no config file, no spec directory. They
    // ignored paths that cannot exist, which reads to the next person as evidence
    // that this repo has browser tests. It does not, and pretending otherwise in
    // config is how somebody concludes a surface is covered.
  ]),
]);

export default eslintConfig;
