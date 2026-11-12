/**
 * Client for the administrator endpoints.
 *
 * Signing in returns a random token. It is sent in the `Authorization` header of
 * every admin request and kept in this tab's session storage, so it is gone when
 * the tab closes and is never sent automatically by the browser (which is what
 * makes cross-site request forgery impossible here). The server ends a session
 * after 30 minutes without requests, at sign-out and at every password change.
 */
import { failure, json, send } from './api'

const STORAGE_KEY = 'lumora.admin.token'

export type AdminStatus = 'supported' | 'partial' | 'unsupported' | 'requires_review'

export interface AdminSession {
  email: string
  must_change_password: boolean
  expires_in: number
  /** Only present right after signing in or changing the password. */
  token: string | null
  /** False when the server cannot save the account to disk. */
  persistent: boolean
}

export interface AdminCheck {
  at: number
  status: AdminStatus
  summary: string
  method: 'extractor' | 'generic' | 'none'
  extractor: string | null
  url: string | null
  title: string | null
  qualities: number
  max_height: number | null
  subtitles: number
  error_code: string | null
  error_message: string | null
  seconds: number | null
}

export interface AdminPlatform {
  id: string
  name: string
  domains: string[]
  builtin: boolean
  expected: 'full' | 'partial' | 'unsupported' | null
  note: string | null
  region: string
  status: AdminStatus
  enabled: boolean
  /** Links from this platform are accepted right now (the switch, plus the server's own rules). */
  active: boolean
  can_enable: boolean
  checking: boolean
  check: AdminCheck | null
  requests_ok: number
  requests_failed: number
}

export interface AdminPlatforms {
  mode: 'platforms' | 'open' | 'allowlist'
  persistent: boolean
  platforms: AdminPlatform[]
}

export interface AdminErrorEntry {
  at: number
  stage: 'analyze' | 'download'
  domain: string
  platform: string | null
  code: string
  message: string
}

export interface AdminOverview {
  version: string
  extractor_version: string
  ffmpeg: string | null
  environment: string
  mode: 'platforms' | 'open' | 'allowlist'
  max_file_size_bytes: number
  max_concurrent_jobs: number
  file_ttl_seconds: number
  running_jobs: number
  queued_jobs: number
  kept_files: number
  uptime_seconds: number
  disk: {
    free_bytes: number
    total_bytes: number
    used_bytes: number
    reserved_bytes: number
    floor_bytes: number
    budget_bytes: number | null
  }
  counts: Record<string, number>
  persistent: boolean
  errors: AdminErrorEntry[]
}

function readToken(): string | null {
  try {
    return sessionStorage.getItem(STORAGE_KEY)
  } catch {
    return null
  }
}

let token: string | null = readToken()

function remember(value: string | null): void {
  token = value
  try {
    if (value) sessionStorage.setItem(STORAGE_KEY, value)
    else sessionStorage.removeItem(STORAGE_KEY)
  } catch {
    /* storage can be unavailable (private mode); the token then lives for this page only */
  }
}

function authorized(init: RequestInit = {}): RequestInit {
  return { ...init, cache: 'no-store', headers: { ...init.headers, ...(token ? { Authorization: `Bearer ${token}` } : {}) } }
}

function body(value: unknown): RequestInit {
  return { method: 'POST', body: JSON.stringify(value) }
}

async function keep(session: Promise<AdminSession>): Promise<AdminSession> {
  const result = await session
  if (result.token) remember(result.token)
  return { ...result, token: null }
}

async function empty(path: string, init: RequestInit): Promise<void> {
  const response = await send(path, authorized(init))
  if (!response.ok) throw await failure(response)
}

const BASE = '/api/v1/admin'

export const adminApi = {
  hasToken: (): boolean => token !== null,
  forget: (): void => remember(null),

  /** Whether the server has an administrator at all. Needs no session. */
  status(signal?: AbortSignal): Promise<{ configured: boolean }> {
    return json<{ configured: boolean }>(`${BASE}/status`, { signal, cache: 'no-store' })
  },
  login(email: string, password: string): Promise<AdminSession> {
    return keep(json<AdminSession>(`${BASE}/login`, { ...body({ email, password }), cache: 'no-store' }))
  },
  session(): Promise<AdminSession> {
    return json<AdminSession>(`${BASE}/session`, authorized())
  },
  async logout(): Promise<void> {
    try {
      await empty(`${BASE}/logout`, { method: 'POST' })
    } finally {
      remember(null)
    }
  },
  changePassword(current: string, next: string): Promise<AdminSession> {
    return keep(json<AdminSession>(`${BASE}/password`, authorized(body({ current_password: current, new_password: next }))))
  },

  overview(): Promise<AdminOverview> {
    return json<AdminOverview>(`${BASE}/overview`, authorized())
  },
  platforms(): Promise<AdminPlatforms> {
    return json<AdminPlatforms>(`${BASE}/platforms`, authorized())
  },
  /** Add a website (or find the platform a link belongs to) and start a compatibility check. */
  add(target: string, name: string | null): Promise<AdminPlatform> {
    return json<AdminPlatform>(`${BASE}/platforms`, authorized(body(name ? { target, name } : { target })))
  },
  check(id: string, url: string | null): Promise<AdminPlatform> {
    return json<AdminPlatform>(`${BASE}/platforms/${encodeURIComponent(id)}/check`, authorized(body(url ? { url } : {})))
  },
  setEnabled(id: string, enabled: boolean): Promise<AdminPlatform> {
    return json<AdminPlatform>(`${BASE}/platforms/${encodeURIComponent(id)}`, authorized({ method: 'PATCH', body: JSON.stringify({ enabled }) }))
  },
  /** Check every platform that is switched on, with sample links. The server runs two at a time. */
  checkAll(): Promise<{ started: number; pending: number }> {
    return json<{ started: number; pending: number }>(`${BASE}/platform-checks`, authorized({ method: 'POST' }))
  },
  remove(id: string): Promise<void> {
    return empty(`${BASE}/platforms/${encodeURIComponent(id)}`, { method: 'DELETE' })
  },
}
