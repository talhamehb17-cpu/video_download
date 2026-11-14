/**
 * The visitor's word that they are 18 or older.
 *
 * The visitor answers once, in the browser, and the answer is remembered on this device
 * for a while. It is what lets the server read a video the platform keeps behind an age
 * question; Lumora never signs in and never invents an answer. It is only ever true for
 * requests that carry it — an id or a link copied out of the page does not include it.
 */

export const AGE_CONSENT_KEY = 'lumora.age-confirmed.v1'
/** The header the API reads the answer from (see backend `app/schemas.py`). */
export const AGE_CONSENT_HEADER = 'X-Lumora-Age-Confirmed'

type Store = Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>
/** The browser's own storage for one site; absent in tests and in privacy modes that refuse it. */
/** Kept in a box the site provides; absent when there is no browser at all. */
let store: Store | null = typeof window === 'undefined' ? null : window.localStorage

function read(key: string): string | null {
  try {
    return store?.getItem(key) ?? null
  } catch {
    return null // storage disabled: the visitor is asked again, never blocked
  }
}

function write(key: string, value: string | null): void {
  try {
    if (value === null) store?.removeItem(key)
    else store?.setItem(key, value)
  } catch {
    /* nothing to remember it with: the question simply comes back */
  }
}

/**
 * Whether the visitor has said they are 18 or older.
 *
 * An answer is kept for at most a day, and at most until the browser is closed
 * (sessionStorage) or for the duration the API suggested. A stored answer past its
 * time is treated as no answer at all.
 */
export function ageConfirmed(now: number = Date.now()): boolean {
  const raw = read(AGE_CONSENT_KEY)
  if (!raw) return false
  try {
    const value = JSON.parse(raw) as { until?: unknown }
    return typeof value.until === 'number' && value.until > now
  } catch {
    return false
  }
}

/** Remember the answer. `ttlSeconds` is the API's suggestion, capped at a day. */
export function rememberAge(ttlSeconds: number, now: number = Date.now()): void {
  const safe = Number.isFinite(ttlSeconds) && ttlSeconds > 0 ? ttlSeconds : 6 * 60 * 60
  const until = now + Math.min(safe, 24 * 60 * 60) * 1000
  write(AGE_CONSENT_KEY, JSON.stringify({ until }))
}

/** Forget the answer: the next adult video asks again. */
export function forgetAge(): void {
  write(AGE_CONSENT_KEY, null)
}

/** For a test: put another store in place (``null`` = no browser storage at all). */
export function useStoreForTests(next: Store | null): void {
  store = next
}

/** Headers for a request that may touch an 18+ video. */
export function ageHeaders(confirmed: boolean = ageConfirmed()): Record<string, string> {
  return confirmed ? { [AGE_CONSENT_HEADER]: 'true' } : {}
}

/** The request body's field, the other way of saying the same thing (see `AnalyzeRequest`). */
export function withAge<T extends object>(body: T, confirmed: boolean = ageConfirmed()): T & { age_confirmed: true } | T {
  return confirmed ? { ...body, age_confirmed: true as const } : body
}
