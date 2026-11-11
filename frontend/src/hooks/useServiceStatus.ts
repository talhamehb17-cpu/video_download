import { useCallback, useEffect, useRef, useState } from 'react'

import { API_CONFIGURED, api, isAbort, type ServiceConfig } from '../lib/api'

export type ServiceState =
  | { status: 'checking'; config: null }
  | { status: 'waking'; config: null; attempt: number }
  | { status: 'online'; config: ServiceConfig }
  | { status: 'offline'; config: null; reason: 'unreachable' | 'not_configured' }

/** Retry for about 90 seconds: hosts that sleep when idle need that long to wake up. */
const RETRY_DELAYS_MS = [1500, 2500, 4000, 6000, 8000, 10000, 12000, 15000, 15000, 15000]

/**
 * Asks the API for its configuration (limits, capabilities, enabled sources).
 * Everything the page says about the service comes from this answer.
 */
export function useServiceStatus(): { state: ServiceState; retry: () => void } {
  const [state, setState] = useState<ServiceState>(
    API_CONFIGURED ? { status: 'checking', config: null } : { status: 'offline', config: null, reason: 'not_configured' },
  )
  const [run, setRun] = useState(0)
  const timer = useRef<number | undefined>(undefined)

  useEffect(() => {
    if (!API_CONFIGURED) return
    const controller = new AbortController()
    let attempt = 0

    const probe = async () => {
      try {
        const config = await api.config(controller.signal)
        setState({ status: 'online', config })
      } catch (error) {
        if (isAbort(error) || controller.signal.aborted) return
        const delay = RETRY_DELAYS_MS[attempt]
        if (delay === undefined) {
          setState({ status: 'offline', config: null, reason: 'unreachable' })
          return
        }
        attempt += 1
        setState({ status: 'waking', config: null, attempt })
        timer.current = window.setTimeout(probe, delay)
      }
    }

    void probe()
    return () => {
      controller.abort()
      window.clearTimeout(timer.current)
    }
  }, [run])

  const retry = useCallback(() => {
    setState({ status: 'checking', config: null })
    setRun((n) => n + 1)
  }, [])
  return { state, retry }
}
