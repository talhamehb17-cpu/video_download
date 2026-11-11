import { useCallback, useEffect, useState } from 'react'

import { API_CONFIGURED, api, type ServiceConfig } from '../lib/api'
import { probeService } from '../lib/serviceProbe'

export type ServiceState =
  | { status: 'checking'; config: null }
  | { status: 'waking'; config: null; attempt: number }
  | { status: 'online'; config: ServiceConfig }
  | { status: 'offline'; config: null; reason: 'unreachable' | 'not_configured' }

/**
 * Asks the API for its configuration (limits, capabilities, enabled sources).
 * Everything the page says about the service comes from this answer.
 */
export function useServiceStatus(): { state: ServiceState; retry: () => void } {
  const [state, setState] = useState<ServiceState>(
    API_CONFIGURED ? { status: 'checking', config: null } : { status: 'offline', config: null, reason: 'not_configured' },
  )
  const [run, setRun] = useState(0)

  useEffect(() => {
    if (!API_CONFIGURED) return
    return probeService(
      (signal) => api.config(signal),
      (event) => {
        if (event.status === 'online') setState({ status: 'online', config: event.config })
        else if (event.status === 'waking') setState({ status: 'waking', config: null, attempt: event.attempt })
        else setState({ status: 'offline', config: null, reason: 'unreachable' })
      },
    )
  }, [run])

  const retry = useCallback(() => {
    setState({ status: 'checking', config: null })
    setRun((n) => n + 1)
  }, [])
  return { state, retry }
}
