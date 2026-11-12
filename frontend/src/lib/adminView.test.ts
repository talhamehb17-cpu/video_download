import { describe, expect, it } from 'vitest'

import type { AdminCheck, AdminPlatform } from './adminApi'
import { checkFacts, filterCounts, filterPlatforms, lockReason, passwordProblem, passwordStrength } from './adminView'
import { formatAgo } from './format'

function platform(overrides: Partial<AdminPlatform>): AdminPlatform {
  return {
    id: 'vimeo', name: 'Vimeo', domains: ['vimeo.com'], builtin: true, expected: 'partial', note: null, region: 'global',
    status: 'partial', enabled: true, active: true, can_enable: true, checking: false, check: null, requests_ok: 0,
    requests_failed: 0, ...overrides,
  }
}

const LIST: AdminPlatform[] = [
  platform({}),
  platform({ id: 'netflix', name: 'Netflix', domains: ['netflix.com'], expected: 'unsupported', status: 'unsupported', enabled: false, active: false, can_enable: false, note: 'Protected with DRM.' }),
  platform({ id: 'ted', name: 'TED', domains: ['ted.com'], enabled: false, active: false }),
  platform({ id: 'site-example-org', name: 'Example', domains: ['example.org'], builtin: false, expected: null, status: 'requires_review', enabled: false, active: false }),
]

describe('platform filters', () => {
  it('counts each group', () => {
    expect(filterCounts(LIST)).toEqual({ all: 4, on: 1, off: 2, review: 1, unsupported: 1, added: 1 })
  })

  it('puts added websites first and searches names and domains', () => {
    expect(filterPlatforms(LIST, 'all', '').map((item) => item.id)).toEqual(['site-example-org', 'vimeo', 'netflix', 'ted'])
    expect(filterPlatforms(LIST, 'all', ' TED ').map((item) => item.id)).toEqual(['ted'])
    expect(filterPlatforms(LIST, 'all', 'example.org').map((item) => item.id)).toEqual(['site-example-org'])
    expect(filterPlatforms(LIST, 'off', '').map((item) => item.id)).toEqual(['site-example-org', 'ted'])
    expect(filterPlatforms(LIST, 'unsupported', 'vimeo')).toEqual([])
  })

  it('explains a locked switch', () => {
    expect(lockReason(LIST[0])).toBeNull()
    expect(lockReason(LIST[1])).toBe('Protected with DRM.')
    expect(lockReason(platform({ status: 'unsupported', can_enable: false }))).toMatch(/Run a check/)
  })
})

describe('check facts', () => {
  const check: AdminCheck = {
    at: 1, status: 'supported', summary: '', method: 'extractor', extractor: 'Vimeo', url: null, title: null, qualities: 6,
    max_height: 1080, subtitles: 1, error_code: null, error_message: null, seconds: 3.26,
  }

  it('describes what was found', () => {
    expect(checkFacts(check)).toEqual(['Dedicated integration (Vimeo)', '6 qualities up to 1080p', '1 subtitle language', 'took 3.3 s'])
    expect(checkFacts({ ...check, method: 'generic', extractor: null, qualities: 1, max_height: null, subtitles: 0, seconds: null })).toEqual([
      'General page reader, no dedicated integration',
      '1 quality',
    ])
    expect(checkFacts({ ...check, method: 'none', qualities: 0, subtitles: 0, seconds: null })).toEqual(['No integration known'])
  })
})

describe('password rules', () => {
  const email = 'Owner@Example.com'

  it('names the first problem', () => {
    expect(passwordProblem('old-password-1', 'short', 'short', email)).toMatch(/at least 12/)
    expect(passwordProblem('old-password-1', 'x'.repeat(129), 'x'.repeat(129), email)).toMatch(/at most 128/)
    expect(passwordProblem('same-password-1', 'same-password-1', 'same-password-1', email)).toMatch(/different/)
    expect(passwordProblem('old-password-1', 'owner@example.com', 'owner@example.com', email)).toMatch(/e-mail/)
    expect(passwordProblem('old-password-1', 'a brand new phrase', 'a brand new phrasE', email)).toMatch(/don't match/)
    expect(passwordProblem('old-password-1', 'a brand new phrase', 'a brand new phrase', email)).toBeNull()
  })

  it('rates length and variety, never above 4', () => {
    expect(passwordStrength('')).toBe(0)
    expect(passwordStrength('short')).toBe(1)
    expect(passwordStrength('aaaaaaaaaaaaaaaa')).toBe(1)
    expect(passwordStrength('correcthorse')).toBe(2)
    expect(passwordStrength('correct horse 42')).toBe(3)
    expect(passwordStrength('Correct horse battery 42!')).toBe(4)
  })
})

describe('formatAgo', () => {
  it('describes how long ago something happened', () => {
    expect(formatAgo(1000, 1010)).toBe('just now')
    expect(formatAgo(1000, 1000 + 5 * 60)).toBe('5 min ago')
    expect(formatAgo(1000, 1000 + 3 * 3600)).toBe('3 h ago')
    expect(formatAgo(1000, 1000 + 86_400)).toBe('1 day ago')
    expect(formatAgo(1000, 1000 + 4 * 86_400)).toBe('4 days ago')
    expect(formatAgo(2000, 1000)).toBe('just now')
  })
})
