/** Pure helpers for the admin panel: labels, filters and the password rules. */
import type { AdminCheck, AdminPlatform, AdminStatus } from './adminApi'

export const ADMIN_STATUS_LABEL: Record<AdminStatus, string> = {
  supported: 'Supported',
  partial: 'Partially supported',
  unsupported: 'Unsupported',
  requires_review: 'Requires review',
}

export type PlatformFilter = 'all' | 'on' | 'off' | 'review' | 'unsupported' | 'added'

export const FILTERS: ReadonlyArray<{ id: PlatformFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'on', label: 'Switched on' },
  { id: 'off', label: 'Switched off' },
  { id: 'review', label: 'Requires review' },
  { id: 'unsupported', label: 'Unsupported' },
  { id: 'added', label: 'Added by you' },
]

export function inFilter(platform: AdminPlatform, filter: PlatformFilter): boolean {
  switch (filter) {
    case 'all':
      return true
    case 'on':
      return platform.active
    case 'off':
      return !platform.active && platform.can_enable
    case 'review':
      return platform.status === 'requires_review'
    case 'unsupported':
      return platform.status === 'unsupported'
    case 'added':
      return !platform.builtin
  }
}

export function filterCounts(platforms: AdminPlatform[]): Record<PlatformFilter, number> {
  const counts: Record<PlatformFilter, number> = { all: 0, on: 0, off: 0, review: 0, unsupported: 0, added: 0 }
  for (const platform of platforms) {
    for (const { id } of FILTERS) if (inFilter(platform, id)) counts[id] += 1
  }
  return counts
}

/** Websites the administrator added come first (they wait for a decision), then the built-in list in its own order. */
export function filterPlatforms(platforms: AdminPlatform[], filter: PlatformFilter, query: string): AdminPlatform[] {
  const needle = query.trim().toLowerCase()
  const matches = platforms.filter(
    (platform) =>
      inFilter(platform, filter) &&
      (!needle || platform.name.toLowerCase().includes(needle) || platform.domains.some((domain) => domain.includes(needle))),
  )
  return [...matches.filter((platform) => !platform.builtin), ...matches.filter((platform) => platform.builtin)]
}

/** What a check observed, as short facts: "Dedicated integration (Vimeo)", "6 qualities up to 1080p"… */
export function checkFacts(check: AdminCheck): string[] {
  const facts: string[] = []
  if (check.method === 'extractor') facts.push(check.extractor ? `Dedicated integration (${check.extractor})` : 'Dedicated integration')
  else if (check.method === 'generic') facts.push('General page reader, no dedicated integration')
  else facts.push('No integration known')
  if (check.qualities > 0) {
    facts.push(`${check.qualities} qualit${check.qualities === 1 ? 'y' : 'ies'}${check.max_height ? ` up to ${check.max_height}p` : ''}`)
  }
  if (check.subtitles > 0) facts.push(`${check.subtitles} subtitle language${check.subtitles === 1 ? '' : 's'}`)
  if (check.seconds != null) facts.push(`took ${check.seconds.toFixed(1)} s`)
  return facts
}

/** Why the switch of a platform cannot be turned on, or null when it can. */
export function lockReason(platform: AdminPlatform): string | null {
  if (platform.can_enable) return null
  if (platform.expected === 'unsupported') return platform.note ?? 'This service can never be downloaded from.'
  return 'The last check found nothing that can be downloaded. Run a check with a link to a public video to change that.'
}

export const PASSWORD_MIN = 12
export const PASSWORD_MAX = 128

/** The first problem with a new password, in words, or null when it can be sent. The server checks again. */
export function passwordProblem(current: string, next: string, confirm: string, email: string): string | null {
  if (next.length < PASSWORD_MIN) return `Use at least ${PASSWORD_MIN} characters.`
  if (next.length > PASSWORD_MAX) return `Use at most ${PASSWORD_MAX} characters.`
  if (next === current) return 'The new password must be different from the current one.'
  if (email && next.trim().toLowerCase() === email.trim().toLowerCase()) return "Don't use your e-mail address as the password."
  if (next !== confirm) return "The two entries of the new password don't match."
  return null
}

/** 0–4: a rough measure of how hard a password is to guess, from its length and variety only. */
export function passwordStrength(password: string): number {
  if (password.length < PASSWORD_MIN) return password.length === 0 ? 0 : 1
  const kinds = [/[a-z]/, /[A-Z]/, /\d/, /[^A-Za-z0-9]/].filter((kind) => kind.test(password)).length
  const distinct = new Set(password).size
  if (distinct < 6) return 1
  let score = 2
  if (password.length >= 16 || kinds >= 3) score += 1
  if (password.length >= 20 && kinds >= 2) score += 1
  return Math.min(4, score)
}
