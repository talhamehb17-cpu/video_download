/** Human-friendly formatting for sizes, times and languages. */

const UNITS = ['B', 'KB', 'MB', 'GB', 'TB'] as const

/**
 * 4803724 -> "4.58 MB". Decimals are kept fixed so a live counter does not jump
 * in width; pass `trim` for static values such as limits ("50 MB", "1.5 GB").
 */
export function formatBytes(bytes: number | null | undefined, options: { trim?: boolean } = {}): string {
  if (bytes == null || !Number.isFinite(bytes) || bytes < 0) return '—'
  let value = bytes
  let unit = 0
  while (value >= 1024 && unit < UNITS.length - 1) {
    value /= 1024
    unit += 1
  }
  const digits = unit === 0 || value >= 100 ? 0 : value >= 10 ? 1 : 2
  const text = value.toFixed(digits)
  return `${options.trim && digits > 0 ? text.replace(/\.?0+$/, '') : text} ${UNITS[unit]}`
}

export function formatSpeed(bytesPerSecond: number | null | undefined): string | null {
  if (!bytesPerSecond || !Number.isFinite(bytesPerSecond) || bytesPerSecond <= 0) return null
  return `${formatBytes(bytesPerSecond)}/s`
}

/** 75 -> "1:15", 3725 -> "1:02:05". */
export function formatDuration(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds <= 0) return null
  const total = Math.round(seconds)
  const h = Math.floor(total / 3600)
  const m = Math.floor((total % 3600) / 60)
  const s = total % 60
  const two = (n: number) => String(n).padStart(2, '0')
  return h > 0 ? `${h}:${two(m)}:${two(s)}` : `${m}:${two(s)}`
}

/** 8 -> "8 s left", 95 -> "2 min left". */
export function formatEta(seconds: number | null | undefined): string | null {
  if (seconds == null || !Number.isFinite(seconds) || seconds < 0) return null
  if (seconds < 1) return 'almost done'
  if (seconds < 60) return `${Math.ceil(seconds)} s left`
  if (seconds < 3600) return `${Math.ceil(seconds / 60)} min left`
  return `${Math.floor(seconds / 3600)} h ${Math.ceil((seconds % 3600) / 60)} min left`
}

/** 1800 -> "30 minutes", 3600 -> "1 hour". */
export function formatSpan(seconds: number): string {
  if (seconds < 90) return `${Math.round(seconds)} seconds`
  if (seconds < 5400) {
    const minutes = Math.round(seconds / 60)
    return `${minutes} minute${minutes === 1 ? '' : 's'}`
  }
  const hours = Math.round((seconds / 3600) * 10) / 10
  return `${hours} hour${hours === 1 ? '' : 's'}`
}

/** 754 -> "12:34" (for countdowns). */
export function formatClock(seconds: number): string {
  const total = Math.max(0, Math.ceil(seconds))
  const m = Math.floor(total / 60)
  const s = total % 60
  return `${m}:${String(s).padStart(2, '0')}`
}

let languageNames: Intl.DisplayNames | null | undefined

/** "pt-BR" -> "Brazilian Portuguese". Falls back to the code itself. */
export function languageName(code: string, fallback?: string | null): string {
  if (languageNames === undefined) {
    try {
      languageNames = new Intl.DisplayNames(['en'], { type: 'language', fallback: 'none' })
    } catch {
      languageNames = null
    }
  }
  const cleaned = code.replace(/_/g, '-').replace(/-orig$/i, '')
  try {
    const name = languageNames?.of(cleaned)
    if (name) return name
  } catch {
    /* not a valid language tag */
  }
  return fallback?.trim() || code
}

/** "www.example.com" from any URL-ish string; null if it does not parse. */
export function hostnameOf(value: string): string | null {
  try {
    const url = new URL(/^[a-z][a-z0-9+.-]*:/i.test(value) ? value : `https://${value}`)
    return url.hostname || null
  } catch {
    return null
  }
}
