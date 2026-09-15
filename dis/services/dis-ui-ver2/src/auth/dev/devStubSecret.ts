// DEV ONLY. Configures the local stub JWT minted at /dev/login.
//
// TREAT THIS SECRET AS PUBLIC. It is a fixed fixture constant, it is committed here, and
// dis-ui-server's StubVerifier accepts tokens signed with it byte-for-byte. Rotating it,
// renaming it or moving it into an env var would change nothing: anything a browser can
// execute, a reader can extract. Its security value is zero and always was.
//
// WHAT MAKES THAT SAFE IS THAT NOTHING PRODUCTION-FACING CAN REACH IT.
//   Frontend: this module is reachable only through '@devAuthSeam', which vite.config.ts
//     resolves to devAuthSeam.dev.tsx for dev/test builds and to a variant importing none of
//     this for deployable builds. scripts/assert-no-dev-auth.mjs then scans dist/ and fails
//     `pnpm build` if the constant below appears in any emitted asset.
//   Backend: StubVerifier runs only when DIS_AUTH_MODE=STUB *and* DIS_ALLOW_STUB_AUTH
//     explicitly declares the process local *and* POSTGRES_URL is loopback. A deployed
//     process crashloops instead.
//
// It shipped in the production bundle until P1-SEC-001 — the deployed v18 asset carried this
// constant, the issuer, and the persona identities, fetchable unauthenticated. The exposure
// was a module-graph problem, not a missing runtime check: signStubToken already refused to
// run in a production build, which stopped OUR code path and did nothing about someone
// reading the key out of the published JavaScript and minting a token themselves.
//
// The issuer and audience match the Customer Master fake (libs/dis-testing fixtures), so the
// stub claim envelope lines up with the real target. verifyToken.ts is the seam where HMAC
// gives way to RS256/JWKS.

export const STUB_SECRET = 'dis-ui-dev-stub-secret-not-for-production'
export const STUB_ISSUER = 'https://customer-master.local'
export const STUB_AUDIENCE = 'dis'
export const STUB_EXPIRY = '8h'
