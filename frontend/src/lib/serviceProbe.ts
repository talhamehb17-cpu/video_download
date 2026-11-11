/**
 * Finding out whether the download service is there.
 *
 * Many small hosts put a service to sleep when nobody uses it and need up to a
 * minute to start it again. Some refuse requests in the meantime, others hold
 * the first request until the service is up. Either way the visitor should be
 * told that it is waking up, and should not be left waiting for ever.
 */

import { isAbort, type ServiceConfig } from './api'

export type ProbeEvent =
  | { status: 'waking'; attempt: number }
  | { status: 'online'; config: ServiceConfig }
  | { status: 'unreachable' }

/** An awake service answers well within this. Past it, say that it is waking up. */
export const SLOW_AFTER_MS = 4000
/** Pauses between attempts when one fails outright. The last value repeats. */
export const RETRY_DELAYS_MS = [1500, 2500, 4000, 6000, 8000, 10000, 12000, 15000]
/** Hosts that sleep when idle need about a minute to start a service. Then give up. */
export const GIVE_UP_AFTER_MS = 120_000

/**
 * Keeps asking for the service's configuration until it answers or time runs out.
 * Reports what happens through `report` and returns a function that stops it.
 */
export function probeService(
  fetchConfig: (signal: AbortSignal) => Promise<ServiceConfig>,
  report: (event: ProbeEvent) => void,
): () => void {
  const controller = new AbortController()
  let attempt = 0
  let settled = false
  let saidWaking = false
  let retryTimer: ReturnType<typeof setTimeout> | undefined

  const slowTimer = setTimeout(() => {
    if (settled || saidWaking) return
    saidWaking = true
    report({ status: 'waking', attempt })
  }, SLOW_AFTER_MS)

  const giveUpTimer = setTimeout(() => {
    if (settled) return
    stop()
    report({ status: 'unreachable' })
  }, GIVE_UP_AFTER_MS)

  function stop() {
    settled = true
    clearTimeout(retryTimer)
    clearTimeout(slowTimer)
    clearTimeout(giveUpTimer)
    controller.abort()
  }

  const ask = async () => {
    try {
      const config = await fetchConfig(controller.signal)
      if (settled) return
      stop()
      report({ status: 'online', config })
    } catch (error) {
      if (settled || isAbort(error)) return
      const delay = RETRY_DELAYS_MS[Math.min(attempt, RETRY_DELAYS_MS.length - 1)]
      attempt += 1
      saidWaking = true
      report({ status: 'waking', attempt })
      retryTimer = setTimeout(() => void ask(), delay)
    }
  }

  void ask()
  return stop
}
