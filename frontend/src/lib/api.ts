/**
 * Typed client for the Lumora API.
 *
 * The base URL comes from VITE_API_BASE_URL at build time. When it is empty the
 * app calls relative `/api/...` paths, which the dev server proxies to a local API.
 */

import { ageHeaders, withAge } from './ageConsent'
import { platformsFromDomains, type PlatformList } from './platforms'

export const API_BASE: string = (import.meta.env.VITE_API_BASE_URL ?? '').trim().replace(/\/+$/, '')

/** False for a production build that was never given an API address. */
export const API_CONFIGURED: boolean = API_BASE !== '' || import.meta.env.DEV

export function apiUrl(path: string): string {
  return `${API_BASE}${path}`
}

// ------------------------------------------------------------------------------ types
export interface Notice {
  code: string
  message: string
}

export interface Quality {
  id: string
  kind: 'video' | 'audio'
  label: string
  container: string
  height: number | null
  width: number | null
  fps: number | null
  video_codec: string | null
  audio_codec: string | null
  has_audio: boolean
  requires_merge: boolean
  filesize: number | null
  filesize_is_estimate: boolean
  bitrate_kbps: number | null
  dynamic_range: string | null
  can_embed_subtitles: boolean
  exceeds_limit: boolean
  recommended: boolean
}

export type SubtitleFormat = 'srt' | 'vtt'

export interface SubtitleTrack {
  id: string
  language: string
  name: string | null
  kind: 'manual' | 'auto'
  formats: SubtitleFormat[]
  embeddable: boolean
}

export interface Analysis {
  id: string
  url: string
  title: string
  uploader: string | null
  duration: number | null
  thumbnail_url: string | null
  source: { domain: string; extractor: string; platform?: string | null }
  qualities: Quality[]
  subtitles: SubtitleTrack[]
  notices: Notice[]
  expires_in: number
  /** The video is for adults only; every request for it carries the visitor's answer. */
  age_restricted?: boolean
}

export type JobStatus = 'queued' | 'running' | 'completed' | 'failed' | 'cancelled' | 'expired' | 'deleted'

export interface JobProgress {
  percent: number | null
  downloaded_bytes: number
  total_bytes: number | null
  speed_bps: number | null
  eta_seconds: number | null
  part: number | null
  parts: number | null
  part_kind: string | null
}

export interface ErrorBody {
  code: string
  message: string
  hint?: string | null
  retry_after?: number | null
  fields?: Array<{ field: string; message: string }> | null
}

export interface Job {
  id: string
  status: JobStatus
  stage: string
  stage_detail: string | null
  queue_position: number | null
  title: string
  quality_label: string
  container: string
  progress: JobProgress
  file: { name: string; size: number; container: string; url: string; expires_in: number } | null
  error: ErrorBody | null
  embedded_subtitles: string[]
  notices: Notice[]
}

export interface ServiceConfig {
  name: string
  version: string
  limits: {
    max_file_size_bytes: number
    max_duration_seconds: number
    file_ttl_seconds: number
    analysis_ttl_seconds: number
  }
  capabilities: {
    merge: boolean
    subtitle_conversion: boolean
    subtitle_embedding: boolean
    subtitle_formats: string[]
    /** The API has the platform list and the admin panel (version 1.1 and later). */
    platform_list?: boolean
    /** The API offers 18+ videos after the visitor confirms their age (version 1.2 and later). */
    age_confirmation?: boolean
  }
  sources: {
    mode: 'platforms' | 'open' | 'allowlist'
    domains: string[]
    examples: Array<{ label: string; source: string; url: string }>
  }
}

// ----------------------------------------------------------------------------- errors
export class ApiError extends Error {
  readonly code: string
  readonly hint: string | null
  readonly status: number
  readonly retryAfter: number | null

  constructor(code: string, message: string, options: { hint?: string | null; status?: number; retryAfter?: number | null } = {}) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.hint = options.hint ?? null
    this.status = options.status ?? 0
    this.retryAfter = options.retryAfter ?? null
  }

  /** The API has no such address: it is older than this website. */
  get isMissingEndpoint(): boolean {
    return this.status === 404 && this.code === 'not_found_route'
  }

  /**
   * Whether sending the same request again could give a different answer.
   * The API answers 422 when the link itself is the problem (wrong, private,
   * not allowed…), so repeating it would only fail the same way.
   */
  get retryable(): boolean {
    return this.status !== 422 && this.status !== 413 && this.code !== 'not_configured'
  }

  /** The service could not be reached at all (as opposed to answering with an error). */
  get isConnectivity(): boolean {
    return this.code === 'network_error' || this.code === 'service_unavailable' || this.code === 'not_configured'
  }
}

export function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError'
}

export function toApiError(error: unknown): ApiError {
  if (error instanceof ApiError) return error
  return new ApiError('internal_error', 'Something unexpected happened.', { hint: 'Please try again.' })
}

function notConfigured(): ApiError {
  return new ApiError('not_configured', "This site isn't connected to a download service yet.", {
    hint: 'The site owner needs to set the API address (VITE_API_BASE_URL) and redeploy.',
  })
}

export async function send(path: string, init: RequestInit = {}): Promise<Response> {
  if (!API_CONFIGURED) throw notConfigured()
  try {
    return await fetch(apiUrl(path), {
      ...init,
      headers: {
        Accept: 'application/json',
        ...(init.body ? { 'Content-Type': 'application/json' } : {}),
        ...init.headers,
      },
    })
  } catch (error) {
    if (isAbort(error)) throw error
    throw new ApiError('network_error', "We couldn't reach the download service.", {
      hint: 'Check your connection, then try again.',
    })
  }
}

export async function failure(response: Response): Promise<ApiError> {
  const isJson = (response.headers.get('content-type') ?? '').includes('application/json')
  if (isJson) {
    try {
      const body = (await response.json()) as { error?: ErrorBody }
      if (body.error?.code && body.error.message) {
        // A rejected request says which fields were wrong; show that instead of nothing.
        const fields = (body.error.fields ?? []).map((item) => `${item.field}: ${item.message}`).join('; ')
        return new ApiError(body.error.code, body.error.message, {
          hint: body.error.hint ?? (fields || null),
          status: response.status,
          retryAfter: body.error.retry_after ?? (Number(response.headers.get('retry-after')) || null),
        })
      }
    } catch {
      /* fall through to the generic message */
    }
  }
  return new ApiError('service_unavailable', "The download service isn't responding properly right now.", {
    hint: 'Please try again in a moment.',
    status: response.status,
  })
}

export async function json<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await send(path, init)
  const isJson = (response.headers.get('content-type') ?? '').includes('application/json')
  if (!response.ok || !isJson) throw await failure(response)
  return (await response.json()) as T
}

/** Read the file name from a Content-Disposition header (RFC 6266 / RFC 5987). */
export function filenameFromDisposition(header: string | null): string | null {
  if (!header) return null
  const extended = /filename\*\s*=\s*UTF-8''([^;]+)/i.exec(header)
  if (extended?.[1]) {
    try {
      return decodeURIComponent(extended[1].trim())
    } catch {
      /* fall back to the plain parameter */
    }
  }
  const plain = /filename\s*=\s*"([^"]*)"/i.exec(header) ?? /filename\s*=\s*([^;]+)/i.exec(header)
  return plain?.[1]?.trim() || null
}

// -------------------------------------------------------------------------- endpoints
export const api = {
  config(signal?: AbortSignal): Promise<ServiceConfig> {
    return json<ServiceConfig>('/api/v1/config', { signal })
  },

  /**
   * The platform list. An API from before the list existed says so in its
   * configuration; it is not asked, and the list is built from the domains it names.
   */
  async platforms(config: ServiceConfig, signal?: AbortSignal): Promise<PlatformList> {
    if (!config.capabilities.platform_list) return platformsFromDomains(config.sources.mode, config.sources.domains)
    return json<PlatformList>('/api/v1/platforms', { signal })
  },

  /**
   * Read a link. `ageConfirmed` is the visitor's own answer, sent with the request: the
   * API keeps no record of who confirmed anything, so every request carries it.
   */
  analyze(url: string, options: { ageConfirmed?: boolean; signal?: AbortSignal } = {}): Promise<Analysis> {
    const { ageConfirmed = false, signal } = options
    return json<Analysis>('/api/v1/analyze', {
      method: 'POST',
      body: JSON.stringify(withAge({ url }, ageConfirmed)),
      headers: ageHeaders(ageConfirmed),
      signal,
    })
  },

  createJob(analysisId: string, qualityId: string, embedSubtitles: string[], ageConfirmed = false): Promise<Job> {
    return json<Job>('/api/v1/jobs', {
      method: 'POST',
      body: JSON.stringify(withAge(
        { analysis_id: analysisId, quality_id: qualityId, embed_subtitles: embedSubtitles },
        ageConfirmed,
      )),
      headers: ageHeaders(ageConfirmed),
    })
  },

  job(id: string, options: { ageConfirmed?: boolean; signal?: AbortSignal } = {}): Promise<Job> {
    const { ageConfirmed = false, signal } = options
    return json<Job>(`/api/v1/jobs/${encodeURIComponent(id)}`, { signal, headers: ageHeaders(ageConfirmed) })
  },

  /** Cancels a running job, or deletes a finished file immediately. */
  cancelJob(id: string, ageConfirmed = false): Promise<Job> {
    return json<Job>(`/api/v1/jobs/${encodeURIComponent(id)}`, { method: 'DELETE', headers: ageHeaders(ageConfirmed) })
  },

  /** The preview image. Fetched in the page, because an `<img>` cannot carry the visitor's answer. */
  async thumbnail(analysisId: string, ageConfirmed = false): Promise<Blob> {
    const path = `/api/v1/analyses/${encodeURIComponent(analysisId)}/thumbnail`
    const response = await send(path, { headers: { Accept: 'image/*', ...ageHeaders(ageConfirmed) } })
    if (!response.ok) throw await failure(response)
    return response.blob()
  },

  /** A finished file, fetched with the visitor's answer so a 403 can be shown in the page. */
  async file(url: string, ageConfirmed = false): Promise<{ blob: Blob; filename: string | null }> {
    const response = await send(url, { headers: { Accept: '*/*', ...ageHeaders(ageConfirmed) } })
    if (!response.ok) throw await failure(response)
    return { blob: await response.blob(), filename: filenameFromDisposition(response.headers.get('content-disposition')) }
  },

  /** Subtitle files are small, so they are fetched here to surface errors in the page. */
  async subtitle(analysisId: string, trackId: string, format: SubtitleFormat): Promise<{ blob: Blob; filename: string }> {
    const path = `/api/v1/analyses/${encodeURIComponent(analysisId)}/subtitles/${encodeURIComponent(trackId)}?format=${format}`
    const response = await send(path, { headers: { Accept: '*/*' } })
    if (!response.ok) throw await failure(response)
    const blob = await response.blob()
    const filename = filenameFromDisposition(response.headers.get('content-disposition')) ?? `subtitles.${format}`
    return { blob, filename }
  },
}

/** Hand a blob to the browser as a download. */
export function saveBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.rel = 'noopener'
  document.body.appendChild(link)
  link.click()
  link.remove()
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000)
}
