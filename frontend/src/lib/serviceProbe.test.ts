import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import { ApiError, type ServiceConfig } from './api'
import { GIVE_UP_AFTER_MS, probeService, SLOW_AFTER_MS, type ProbeEvent } from './serviceProbe'

const CONFIG = { name: 'Lumora API', version: '1.0.0' } as ServiceConfig
const unreachable = () => new ApiError('network_error', "We couldn't reach the download service.")

/** A request that only ends when the caller gives up on it, like one a sleeping host holds. */
const held = (signal: AbortSignal) =>
  new Promise<ServiceConfig>((_, reject) => {
    signal.addEventListener('abort', () => reject(new DOMException('Aborted', 'AbortError')))
  })

const after = (ms: number, value: ServiceConfig) => new Promise<ServiceConfig>((resolve) => setTimeout(() => resolve(value), ms))

describe('probeService', () => {
  let events: ProbeEvent[]
  const report = (event: ProbeEvent) => events.push(event)
  const statuses = () => events.map((event) => event.status)

  beforeEach(() => {
    vi.useFakeTimers()
    events = []
  })
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reports a service that answers at once, and then stays quiet', async () => {
    const fetchConfig = vi.fn(async () => CONFIG)
    probeService(fetchConfig, report)
    await vi.advanceTimersByTimeAsync(0)
    expect(events).toEqual([{ status: 'online', config: CONFIG }])

    await vi.advanceTimersByTimeAsync(GIVE_UP_AFTER_MS * 2)
    expect(events).toHaveLength(1)
    expect(fetchConfig).toHaveBeenCalledTimes(1)
  })

  it('says "waking" when the host holds the first request, then reports the answer', async () => {
    probeService(() => after(30_000, CONFIG), report)

    await vi.advanceTimersByTimeAsync(SLOW_AFTER_MS - 1)
    expect(events).toEqual([])
    await vi.advanceTimersByTimeAsync(1)
    expect(events).toEqual([{ status: 'waking', attempt: 0 }])

    await vi.advanceTimersByTimeAsync(30_000)
    expect(statuses()).toEqual(['waking', 'online'])
  })

  it('keeps trying while the host refuses requests, with growing pauses', async () => {
    const fetchConfig = vi
      .fn<(signal: AbortSignal) => Promise<ServiceConfig>>()
      .mockRejectedValueOnce(unreachable())
      .mockRejectedValueOnce(unreachable())
      .mockResolvedValue(CONFIG)
    probeService(fetchConfig, report)

    await vi.advanceTimersByTimeAsync(0)
    expect(events).toEqual([{ status: 'waking', attempt: 1 }])
    await vi.advanceTimersByTimeAsync(1499)
    expect(fetchConfig).toHaveBeenCalledTimes(1)
    await vi.advanceTimersByTimeAsync(1)
    expect(fetchConfig).toHaveBeenCalledTimes(2)
    expect(events.at(-1)).toEqual({ status: 'waking', attempt: 2 })

    await vi.advanceTimersByTimeAsync(2500)
    expect(fetchConfig).toHaveBeenCalledTimes(3)
    expect(statuses()).toEqual(['waking', 'waking', 'online'])

    // nothing fires later: not the "slow" notice, not the time limit
    await vi.advanceTimersByTimeAsync(GIVE_UP_AFTER_MS)
    expect(events).toHaveLength(3)
  })

  it('gives up after two minutes of refusals and stops asking', async () => {
    const fetchConfig = vi.fn(async () => {
      throw unreachable()
    })
    probeService(fetchConfig, report)

    await vi.advanceTimersByTimeAsync(GIVE_UP_AFTER_MS - 1)
    expect(new Set(statuses())).toEqual(new Set(['waking']))
    const attempts = fetchConfig.mock.calls.length
    expect(attempts).toBeGreaterThan(8)

    await vi.advanceTimersByTimeAsync(1)
    expect(events.at(-1)).toEqual({ status: 'unreachable' })

    await vi.advanceTimersByTimeAsync(GIVE_UP_AFTER_MS)
    expect(fetchConfig).toHaveBeenCalledTimes(attempts)
    expect(statuses().filter((status) => status === 'unreachable')).toHaveLength(1)
  })

  it('gives up on a request that is held for ever, and cancels it', async () => {
    let signal: AbortSignal | undefined
    probeService((s) => {
      signal = s
      return held(s)
    }, report)

    await vi.advanceTimersByTimeAsync(GIVE_UP_AFTER_MS)
    expect(statuses()).toEqual(['waking', 'unreachable'])
    expect(signal?.aborted).toBe(true)
  })

  it('stops completely when asked to', async () => {
    let signal: AbortSignal | undefined
    const fetchConfig = vi.fn((s: AbortSignal) => {
      signal = s
      return held(s)
    })
    const stop = probeService(fetchConfig, report)
    await vi.advanceTimersByTimeAsync(1000)
    stop()

    await vi.advanceTimersByTimeAsync(GIVE_UP_AFTER_MS * 2)
    expect(events).toEqual([])
    expect(signal?.aborted).toBe(true)
    expect(fetchConfig).toHaveBeenCalledTimes(1)
  })
})
