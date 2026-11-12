import { useCallback, useEffect, useRef, useState } from 'react'

import { API_CONFIGURED, api, isAbort, type ServiceConfig } from '../lib/api'
import type { PlatformList } from '../lib/platforms'
import { probeService } from '../lib/serviceProbe'

export type ServiceState =
  | { status: 'checking'; config: null }
  | { status: 'waking'; config: null; attempt: number }
  /** `platforms` is null only when the service has a platform list but it could not be fetched. */
  | { status: 'online'; config: ServiceConfig; platforms: PlatformList | null }
  | { status: 'offline'; config: null; reason: 'unreachable' | 'not_configured' }

/**
 * Asks the API for its configuration (limits, capabilities, enabled sources).
 * Everything the page says about the service comes from this answer.
 */
export function useServiceStatus(): {
  state: ServiceState
  retry: () => void
  /** Fetch the platform list again and return it; null when that was not possible. */
  refreshPlatforms: () => Promise<PlatformList | null>
} {
  const [state, setState] = useState<ServiceState>(
    API_CONFIGURED ? { status: 'checking', config: null } : { status: 'offline', config: null, reason: 'not_configured' },
  )
  const [run, setRun] = useState(0)

  useEffect(() => {
    if (!API_CONFIGURED) return
    const lists = new AbortController()
    const stop = probeService(
      (signal) => api.config(signal),
      (event) => {
        if (event.status === 'online') {
          // The page speaks about platforms as soon as it is online, so the list is
          // fetched first: showing a guess for a moment would put wrong numbers on screen.
          const config = event.config
          api.platforms(config, lists.signal).then(
            (platforms) => setState({ status: 'online', config, platforms }),
            (error: unknown) => {
              if (!isAbort(error)) setState({ status: 'online', config, platforms: null })
            },
          )
        }
        else if (event.status === 'waking') setState({ status: 'waking', config: null, attempt: event.attempt })
        else setState({ status: 'offline', config: null, reason: 'unreachable' })
      },
    )
    return () => {
      lists.abort()
      stop()
    }
  }, [run])

  const retry = useCallback(() => {
    setState({ status: 'checking', config: null })
    setRun((n) => n + 1)
  }, [])

  const latest = useRef(state)
  useEffect(() => {
    latest.current = state
  }, [state])
  const refreshPlatforms = useCallback(async (): Promise<PlatformList | null> => {
    const current = latest.current
    if (current.status !== 'online') return null
    try {
      const platforms = await api.platforms(current.config)
      setState((now) => (now.status === 'online' ? { ...now, platforms } : now))
      return platforms
    } catch {
      return null
    }
  }, [])

  return { state, retry, refreshPlatforms }
}
