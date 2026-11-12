import { useCallback, useEffect, useState } from 'react'

import { adminApi, type AdminSession } from '../lib/adminApi'
import { ApiError, api, toApiError } from '../lib/api'

/**
 * Where the admin page is:
 *
 *   boot -> unavailable (API unreachable, too old, or admin switched off)
 *        -> login -> password (the initial password must be replaced) -> panel
 *
 * A session that ends (30 minutes without requests, or a restart of the API)
 * brings the page back to `login` from wherever it was.
 */
export type AdminView =
  | { name: 'boot' }
  | { name: 'unavailable'; reason: 'unreachable' | 'old_api' | 'not_configured'; version: string | null; error: ApiError | null }
  | { name: 'login'; notice: string | null }
  | { name: 'password'; session: AdminSession }
  | { name: 'panel'; session: AdminSession }

export interface Admin {
  view: AdminView
  retry: () => void
  /** Rejects with an `ApiError` the form can show. */
  signIn: (email: string, password: string) => Promise<void>
  changePassword: (current: string, next: string) => Promise<void>
  signOut: () => Promise<void>
  /** Runs an admin request. When the session has ended the page returns to the sign-in form. */
  call: <T>(request: () => Promise<T>) => Promise<T>
}

const SESSION_ENDED = 'Your session has ended. Please sign in again.'

function afterSignIn(session: AdminSession): AdminView {
  return session.must_change_password ? { name: 'password', session } : { name: 'panel', session }
}

export function useAdmin(): Admin {
  const [view, setView] = useState<AdminView>({ name: 'boot' })
  const [run, setRun] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    const show = (next: AdminView) => {
      if (!controller.signal.aborted) setView(next)
    }
    void (async () => {
      let version: string | null = null
      try {
        const config = await api.config(controller.signal)
        version = config.version
        // The panel needs an API that has it. Older ones say so by what they leave out.
        if (!config.capabilities.platform_list) return show({ name: 'unavailable', reason: 'old_api', version, error: null })
      } catch (error) {
        return show({ name: 'unavailable', reason: 'unreachable', version, error: toApiError(error) })
      }
      try {
        const { configured } = await adminApi.status(controller.signal)
        if (!configured) return show({ name: 'unavailable', reason: 'not_configured', version, error: null })
        // Nobody is signed in on this device: there is nothing to ask the server about.
        if (!adminApi.hasToken()) return show({ name: 'login', notice: null })
        show(afterSignIn(await adminApi.session()))
      } catch (error) {
        const problem = toApiError(error)
        if (problem.code === 'admin_not_configured') show({ name: 'unavailable', reason: 'not_configured', version, error: problem })
        else if (problem.code === 'not_authenticated') {
          adminApi.forget()
          show({ name: 'login', notice: SESSION_ENDED })
        } else show({ name: 'unavailable', reason: problem.isMissingEndpoint ? 'old_api' : 'unreachable', version, error: problem })
      }
    })()
    return () => controller.abort()
  }, [run])

  const retry = useCallback(() => {
    setView({ name: 'boot' })
    setRun((n) => n + 1)
  }, [])

  const signIn = useCallback(async (email: string, password: string) => {
    try {
      setView(afterSignIn(await adminApi.login(email, password)))
    } catch (error) {
      const problem = toApiError(error)
      if (problem.code === 'admin_not_configured') setView({ name: 'unavailable', reason: 'not_configured', version: null, error: problem })
      else if (problem.isMissingEndpoint) setView({ name: 'unavailable', reason: 'old_api', version: null, error: null })
      throw problem
    }
  }, [])

  const call = useCallback(async <T>(request: () => Promise<T>): Promise<T> => {
    try {
      return await request()
    } catch (error) {
      const problem = toApiError(error)
      if (problem.code === 'not_authenticated') {
        adminApi.forget()
        setView({ name: 'login', notice: SESSION_ENDED })
      } else if (problem.code === 'password_change_required') {
        setRun((n) => n + 1) // ask the server where this session stands
      }
      throw problem
    }
  }, [])

  const changePassword = useCallback(
    async (current: string, next: string) => {
      // Every older session ends here; the answer carries the token of the new one.
      const session = await call(() => adminApi.changePassword(current, next))
      setView({ name: 'panel', session })
    },
    [call],
  )

  const signOut = useCallback(async () => {
    try {
      await adminApi.logout()
    } catch {
      /* the token is forgotten on this device either way */
    }
    setView({ name: 'login', notice: 'You are signed out.' })
  }, [])

  return { view, retry, signIn, changePassword, signOut, call }
}
