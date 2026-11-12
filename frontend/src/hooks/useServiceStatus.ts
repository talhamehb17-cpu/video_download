import { useCallback, useEffect, useRef, useState } from 'react'

import { API_CONFIGURED, api, type ServiceConfig } from '../lib/api'
import { platformsFromDomains, type PlatformList } from '../lib/platforms'
import { probeService } from '../lib/serviceProbe'

export type ServiceState =
  | { status: 'checking'; config: null }
  | { status: 'waking'; config: null; attempt: number }
  | { status: 'online'; config: ServiceConfig; platforms: PlatformList }
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
          // The site is usable as soon as the configuration is known; the platform
          // list replaces this first guess when it arrives.
          const config = event.config
          setState({ status: 'online', config, platforms: platformsFromDomains(config.sources.mode, config.sources.domains) })
          api.platforms(config, lists.signal).then(
            (platforms) => setState({ status: 'online', config, platforms }),
            () => undefined,
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
