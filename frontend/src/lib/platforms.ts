/**
 * Platforms as the website knows them, and matching a pasted link to one.
 *
 * The list comes from the API (`GET /api/v1/platforms`). Matching here only gives
 * the visitor an early hint while typing; the server decides when a link is sent.
 */

export type PlatformStatus = 'supported' | 'partial' | 'unsupported'

export interface Platform {
  id: string
  name: string
  /** Addresses of the platform. "name.*" also covers country versions (name.co.uk). */
  domains: string[]
  status: PlatformStatus
  /** Links from this platform are accepted right now. */
  enabled: boolean
  /** The last compatibility check on this server read a public video from this platform. */
  verified?: boolean
  /** When the last check that tested a link ran (Unix seconds). With `verified` false, it did not get a video. */
  checked_at?: number | null
  note: string | null
  region: string
}

export interface PlatformList {
  mode: 'platforms' | 'open' | 'allowlist'
  platforms: Platform[]
}

const COUNTRY_TAIL = /^[a-z]{2,3}(\.[a-z]{2})?$/

/** True when `host` is `pattern` or one of its sub-domains. */
export function hostMatches(host: string, pattern: string): boolean {
  if (pattern.endsWith('.*')) {
    const name = pattern.slice(0, -2)
    const labels = host.split('.')
    return labels.slice(0, -1).some((label, index) => label === name && COUNTRY_TAIL.test(labels.slice(index + 1).join('.')))
  }
  return host === pattern || host.endsWith(`.${pattern}`)
}

/** The host name in what someone typed or pasted, or null while it is not a link yet. */
export function hostOf(text: string): string | null {
  const trimmed = text.trim()
  if (!trimmed || /\s/.test(trimmed)) return null
  const withScheme = /^[a-z][a-z0-9+.-]*:\/\//i.test(trimmed) ? trimmed : `https://${trimmed}`
  try {
    const host = new URL(withScheme).hostname.toLowerCase().replace(/\.$/, '')
    return host.includes('.') && !/^[\d.]+$/.test(host) ? host : null
  } catch {
    return null
  }
}

/** The platform a link belongs to. The most specific address wins. */
export function matchPlatform(platforms: readonly Platform[], text: string): Platform | null {
  const host = hostOf(text)
  if (!host) return null
  let best: { score: number; platform: Platform } | null = null
  for (const platform of platforms) {
    for (const domain of platform.domains) {
      if (hostMatches(host, domain) && (!best || domain.length > best.score)) best = { score: domain.length, platform }
    }
  }
  return best?.platform ?? null
}

export type Detection =
  | { kind: 'none' }
  | { kind: 'platform'; platform: Platform }
  /** A real-looking link to a website that is not on the list. */
  | { kind: 'unknown'; host: string }

/** What to tell the visitor about the link in the field. */
export function detect(list: PlatformList | null, text: string): Detection {
  const host = hostOf(text)
  if (!list || !host) return { kind: 'none' }
  const platform = matchPlatform(list.platforms, text)
  if (platform) return { kind: 'platform', platform }
  // In "open" mode unknown websites are tried anyway, so there is nothing to warn about.
  return list.mode === 'open' ? { kind: 'none' } : { kind: 'unknown', host: host.replace(/^www\./, '') }
}

const OPEN_SOURCE_NAMES: Record<string, string> = {
  'archive.org': 'Internet Archive',
  'wikimedia.org': 'Wikimedia Commons',
  'nasa.gov': 'NASA',
  'media.ccc.de': 'media.ccc.de',
  'blender.org': 'Blender',
}

/**
 * For an API from before the platform list existed: build the list from the
 * domains its configuration names, so the rest of the site has one shape to work with.
 */
export function platformsFromDomains(mode: PlatformList['mode'], domains: readonly string[]): PlatformList {
  return {
    mode,
    platforms: domains.map((domain) => ({
      id: domain.replace(/[^a-z0-9]+/g, '-'),
      name: OPEN_SOURCE_NAMES[domain] ?? domain,
      domains: [domain],
      status: 'supported',
      enabled: true,
      // no `verified`: such an API has no compatibility checks, so there is nothing to say about them
      note: null,
      region: 'open',
    })),
  }
}

export const STATUS_LABEL: Record<PlatformStatus, string> = {
  supported: 'Supported',
  partial: 'Partially supported',
  unsupported: 'Unsupported',
}

/** Platforms visitors can use, best first, then by name. */
export function usable(list: PlatformList | null): Platform[] {
  if (!list) return []
  const rank = { supported: 0, partial: 1, unsupported: 2 } as const
  return list.platforms
    .filter((platform) => platform.enabled && platform.status !== 'unsupported')
    .sort((a, b) => rank[a.status] - rank[b.status] || a.name.localeCompare(b.name))
}

/** "YouTube, Vimeo, TikTok and 37 more" */
export function summarise(platforms: readonly Platform[], shown = 4): string {
  const names = platforms.slice(0, shown).map((platform) => platform.name)
  const rest = platforms.length - names.length
  if (names.length === 0) return ''
  if (rest > 0) return `${names.join(', ')} and ${rest} more`
  return names.length === 1 ? names[0]! : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`
}

/** Usable platforms with the internationally known ones first, in the order the service lists them. */
export function featured(list: PlatformList | null): Platform[] {
  if (!list) return []
  const rank = (platform: Platform) => (platform.region === 'global' ? 0 : platform.region === 'open' ? 2 : 1)
  return list.platforms
    .filter((platform) => platform.enabled && platform.status !== 'unsupported')
    .map((platform, index) => ({ platform, index }))
    .sort((a, b) => rank(a.platform) - rank(b.platform) || a.index - b.index)
    .map((item) => item.platform)
}

export interface Refusal {
  code: 'platform_unsupported' | 'platform_disabled' | 'domain_not_allowed'
  message: string
  hint: string | null
}

/**
 * Why the service would decline this link, judged from its own platform list.
 * Null when it would be accepted, or when that cannot be told for certain from
 * here: only in "platforms" mode is the list exactly what the service enforces.
 * In every other case the link is sent and the service answers for itself.
 */
export function refusalFor(list: PlatformList | null, text: string): Refusal | null {
  if (list?.mode !== 'platforms') return null
  const found = detect(list, text)
  if (found.kind === 'unknown') {
    return {
      code: 'domain_not_allowed',
      message: `${found.host} isn't a platform this service works with.`,
      hint: 'Only the platforms on the list can be processed.',
    }
  }
  if (found.kind !== 'platform' || found.platform.enabled) return null
  const { platform } = found
  if (platform.status === 'unsupported') {
    return { code: 'platform_unsupported', message: `${platform.name} videos can't be downloaded.`, hint: platform.note }
  }
  return {
    code: 'platform_disabled',
    message: `${platform.name} is switched off on this service.`,
    hint: 'The operator of this service has switched it off.',
  }
}
