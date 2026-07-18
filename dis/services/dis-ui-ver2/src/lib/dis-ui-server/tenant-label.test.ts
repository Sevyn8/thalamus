import { describe, expect, it } from 'vitest'

import { SYSTEM_TENANT, matchesTenant, tenantFull, tenantName, tenantShort } from './tenant-label'

const TID = '0190ac10-1a01-7001-8a01-0000000000a1'
const SHORT = '…0000000000a1'

// Chunk 9-FE: tenantName prefers the mirrored name and falls back HONESTLY to the shortened UUID.
describe('tenantName (Chunk 9-FE display helper)', () => {
  it('returns the mirrored name when the backend serves one', () => {
    expect(tenantName('Buc-ees', TID)).toBe('Buc-ees')
  })

  it('falls back to the shortened UUID when tenant_name is null (older/unmirrored)', () => {
    expect(tenantName(null, TID)).toBe(SHORT)
    expect(tenantName(null, TID)).toBe(tenantShort(TID))
  })

  it('falls back when tenant_name is undefined (a backend that predates Chunk 9) or empty/whitespace', () => {
    expect(tenantName(undefined, TID)).toBe(SHORT)
    expect(tenantName('', TID)).toBe(SHORT)
    expect(tenantName('   ', TID)).toBe(SHORT)
  })

  it('a null tenant_id (audit system row) renders "System / platform", never fabricated', () => {
    expect(tenantName(null, null)).toBe('System / platform')
    expect(tenantName(undefined, null)).toBe('System / platform')
    // The full-id tooltip stays the honest system marker.
    expect(tenantFull(null)).toBe('system / platform (no tenant)')
  })

  it('does not change the full-UUID tooltip (still the raw id)', () => {
    expect(tenantFull(TID)).toBe(TID)
  })

  it('is display-only: matchesTenant still keys on tenant_id, unaffected by the name', () => {
    // Filtering logic is unchanged — a name never participates in matching (value stays tenant_id).
    expect(matchesTenant(TID, TID)).toBe(true)
    expect(matchesTenant(TID, '0190ac10-1a01-7001-8a01-0000000000b2')).toBe(false)
    expect(matchesTenant(null, SYSTEM_TENANT)).toBe(true)
  })
})
