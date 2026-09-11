// DEV ONLY. These constants configure the local stub JWT minted at /dev/login.
//
// =============================================================================================
// THESE CONSTANTS SHIP IN THE PRODUCTION BUNDLE TODAY. THAT IS NOT A HYPOTHETICAL.
// =============================================================================================
// Measured, not reasoned about: the deployed v18 asset at
// /assets/index-Dk29gPmb.js on dis-ui-ver2-697546531605.asia-south1.run.app, fetched
// UNAUTHENTICATED on 2026-08-15, contains STUB_SECRET and STUB_ISSUER once each, along with the
// persona identities from personas.ts.
//
// THE COMMENT HERE USED TO SAY THE OPPOSITE, and the way it was wrong is worth keeping. It said
// the signer "refuses to run in a production build, so this secret can never mint a token
// outside dev". The refusal at signStubToken.ts:15 is real, and it is a check on OUR code path.
// It does nothing about somebody reading the secret out of the published JavaScript and minting
// a token themselves with any JWT library. dis-ui-server's StubVerifier would accept it and its
// claims drive RLS, so the forged token is a tenant-scoped read. A guard's scope and a guard's
// existence are different things, and that sentence conflated them.
//
// WHY IT STILL SHIPS AFTER THE COMMIT THAT WROTE THIS. Excluding it needs a build-time change,
// and the module graph makes that bigger than it looks: App.tsx:8 statically imports
// AuthProvider, which reaches PERSONAS at AuthProvider.tsx:7 and STUB_SECRET through
// verifyToken.ts:5, and App.tsx:82 picks its provider with isRealMode() at RUNTIME so both
// providers are bundled. Those are fixture-mode auth, which is its own slice. An exclusion that
// covered only the /dev/login persona picker was built and REJECTED: it removed the picker and
// left all three strings in dist/, which would have read as a fix while changing nothing.
//
// WHAT PROTECTS THE ESTATE MEANWHILE is on the other side: dis-ui-server now defaults to the
// AUTH0 verifier rather than the stub, and refuses STUB entirely unless its database is
// loopback. A forged token needs a service willing to verify it.
//
// In real mode the stub is replaced by Customer Master tokens verified against a JWKS key set.
//
// The issuer and audience match the Customer Master fake
// (libs/dis-testing fixtures: iss "https://customer-master.local", aud "dis"), so
// the stub claim envelope lines up with the provisional target. The signing stays
// HMAC here; verifyToken.ts is the seam for the RS256/JWKS swap.

export const STUB_SECRET = 'dis-ui-dev-stub-secret-not-for-production'
export const STUB_ISSUER = 'https://customer-master.local'
export const STUB_AUDIENCE = 'dis'
export const STUB_EXPIRY = '8h'
