// DEV ONLY. These constants configure the local stub JWT minted at /dev/login.
//
// HOW THIS IS ACTUALLY KEPT OUT OF PRODUCTION, corrected. This comment used to say the
// signer's refusal to run in a production build meant "this secret can never mint a token
// outside dev". That was false in the way that matters. The refusal at signStubToken.ts:15 is
// a check on OUR code path; it does nothing about the secret itself, which was a string
// literal in the shipped bundle. Anyone could read it out of the published asset and mint a
// token with any JWT library, and the stub verifier would accept it, and its claims drive RLS.
// It was measured in the deployed v18 bundle, not theorised.
//
// THE PROTECTION IS NOW BUILD-TIME EXCLUSION. routes/DevLogin.tsx reaches this module only
// through a dynamic import gated on import.meta.env.PROD, so Rollup drops the branch and emits
// no chunk containing these constants for a production build. The runtime refusal in the
// signer stays as a second layer; it is not the protection.
//
// In real mode the stub is replaced by Customer Master tokens verified against a JWKS key set
// (decisions.md D25).
//
// The issuer and audience match Sanjeev's slice-2 Customer Master fake
// (libs/dis-testing fixtures: iss "https://customer-master.local", aud "dis"), so
// the stub claim envelope lines up with the provisional target. The signing stays
// HMAC here; the RS256/JWKS swap is slice 13 (verifyToken.ts is the seam).

export const STUB_SECRET = 'dis-ui-dev-stub-secret-not-for-production'
export const STUB_ISSUER = 'https://customer-master.local'
export const STUB_AUDIENCE = 'dis'
export const STUB_EXPIRY = '8h'
