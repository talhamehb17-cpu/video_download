import { describe, expect, it } from 'vitest'

import { ApiError, filenameFromDisposition, toApiError } from './api'

describe('filenameFromDisposition', () => {
  it('prefers the UTF-8 name', () => {
    const header = "attachment; filename=\"Ete Paris.mp4\"; filename*=UTF-8''%C3%89t%C3%A9%20Paris%20%E6%97%A5%E6%9C%AC.mp4"
    expect(filenameFromDisposition(header)).toBe('Été Paris 日本.mp4')
  })
  it('falls back to the plain name', () => {
    expect(filenameFromDisposition('attachment; filename="clip (en).srt"')).toBe('clip (en).srt')
    expect(filenameFromDisposition('attachment; filename=clip.vtt')).toBe('clip.vtt')
    expect(filenameFromDisposition("attachment; filename=\"a.srt\"; filename*=UTF-8''%E0%A4%A")).toBe('a.srt')
  })
  it('returns null when absent', () => {
    expect(filenameFromDisposition(null)).toBeNull()
    expect(filenameFromDisposition('inline')).toBeNull()
  })
})

describe('ApiError', () => {
  it('knows connectivity failures', () => {
    expect(new ApiError('network_error', 'x').isConnectivity).toBe(true)
    expect(new ApiError('not_configured', 'x').isConnectivity).toBe(true)
    expect(new ApiError('invalid_url', 'x', { status: 422 }).isConnectivity).toBe(false)
  })
  it('offers a retry only when asking again could change the answer', () => {
    // the link itself is the problem: same request, same answer
    expect(new ApiError('domain_not_allowed', 'x', { status: 422 }).retryable).toBe(false)
    expect(new ApiError('private_content', 'x', { status: 422 }).retryable).toBe(false)
    expect(new ApiError('payload_too_large', 'x', { status: 413 }).retryable).toBe(false)
    expect(new ApiError('not_configured', 'x').retryable).toBe(false)
    // transient: worth another go
    expect(new ApiError('rate_limited', 'x', { status: 429 }).retryable).toBe(true)
    expect(new ApiError('source_timeout', 'x', { status: 504 }).retryable).toBe(true)
    expect(new ApiError('server_busy', 'x', { status: 503 }).retryable).toBe(true)
    expect(new ApiError('analysis_expired', 'x', { status: 410 }).retryable).toBe(true)
    expect(new ApiError('network_error', 'x').retryable).toBe(true)
  })
  it('wraps unknown errors', () => {
    const original = new ApiError('rate_limited', 'slow down', { retryAfter: 5 })
    expect(toApiError(original)).toBe(original)
    expect(toApiError(new TypeError('boom')).code).toBe('internal_error')
  })
})
