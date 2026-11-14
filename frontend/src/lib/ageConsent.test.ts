import { afterEach, beforeEach, describe, expect, it } from 'vitest'

import {
  AGE_CONSENT_HEADER,
  AGE_CONSENT_KEY,
  ageConfirmed,
  ageHeaders,
  forgetAge,
  rememberAge,
  useStoreForTests,
  withAge,
} from './ageConsent'

/** A storage that behaves like the browser's, without a browser. */
function memoryStore(): Storage {
  const items = new Map<string, string>()
  return {
    get length() {
      return items.size
    },
    clear: () => items.clear(),
    getItem: (key: string) => items.get(key) ?? null,
    key: (index: number) => [...items.keys()][index] ?? null,
    removeItem: (key: string) => void items.delete(key),
    setItem: (key: string, value: string) => void items.set(key, value),
  }
}

describe('the visitor’s age answer', () => {
  let store: Storage
  beforeEach(() => {
    store = memoryStore()
    useStoreForTests(store)
  })
  afterEach(() => useStoreForTests(null))

  it('is not given until the visitor says so', () => {
    expect(ageConfirmed()).toBe(false)
    expect(ageHeaders()).toEqual({})
    expect(withAge({ url: 'https://example.com/v' })).toEqual({ url: 'https://example.com/v' })
  })

  it('is sent as the header and as the field once it is given', () => {
    rememberAge(21600)
    expect(ageConfirmed()).toBe(true)
    expect(ageHeaders()).toEqual({ [AGE_CONSENT_HEADER]: 'true' })
    expect(withAge({ url: 'u' })).toEqual({ url: 'u', age_confirmed: true })
  })

  it('expires on its own', () => {
    const start = Date.now()
    rememberAge(60, start)
    expect(ageConfirmed(start + 59_000)).toBe(true)
    expect(ageConfirmed(start + 61_000)).toBe(false)
    expect(ageHeaders(ageConfirmed(start + 61_000))).toEqual({})
  })

  it('is kept for no longer than a day, whatever the API suggests', () => {
    const start = Date.now()
    rememberAge(30 * 24 * 60 * 60, start)
    expect(ageConfirmed(start + 23.9 * 60 * 60 * 1000)).toBe(true)
    expect(ageConfirmed(start + 24.1 * 60 * 60 * 1000)).toBe(false)
  })

  it('falls back to six hours when the API suggests nothing sensible', () => {
    const start = Date.now()
    rememberAge(Number.NaN, start)
    expect(ageConfirmed(start + 5 * 60 * 60 * 1000)).toBe(true)
    expect(ageConfirmed(start + 7 * 60 * 60 * 1000)).toBe(false)
  })

  it('ignores a stored value it cannot read', () => {
    store.setItem(AGE_CONSENT_KEY, 'not json')
    expect(ageConfirmed()).toBe(false)
    store.setItem(AGE_CONSENT_KEY, JSON.stringify({ until: 'soon' }))
    expect(ageConfirmed()).toBe(false)
  })

  it('can be forgotten', () => {
    rememberAge(21600)
    forgetAge()
    expect(ageConfirmed()).toBe(false)
    expect(store.getItem(AGE_CONSENT_KEY)).toBeNull()
  })
})
