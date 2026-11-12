import { CircleCheck, KeyRound, RefreshCw, TriangleAlert } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import type { Admin } from '../../hooks/useAdmin'
import { useClock } from '../../hooks/useCountdown'
import { adminApi, type AdminOverview, type AdminPlatform, type AdminPlatforms, type AdminSession } from '../../lib/adminApi'
import { toApiError, type ApiError } from '../../lib/api'
import { Button } from '../ui/Button'
import { Overview } from './Overview'
import { PasswordForm } from './PasswordForm'
import { PlatformManager } from './PlatformManager'

const POLL_MS = 2500

function Skeleton({ className }: { className: string }) {
  return <div aria-hidden className={`glass animate-pulse rounded-2xl ${className}`} />
}

/** Everything behind the sign-in: how the service is doing, and the platform list. */
export function Panel({ session, admin }: { session: AdminSession; admin: Admin }) {
  const { call, changePassword } = admin
  const now = useClock(15_000)
  const [overview, setOverview] = useState<AdminOverview | null>(null)
  const [list, setList] = useState<AdminPlatforms | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [changing, setChanging] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  // One request at a time. An answer that was on its way while the list was
  // changed here is older than that change, so its list is dropped and asked again.
  const inFlight = useRef(false)
  const again = useRef(false)
  const revision = useRef(0)

  const load = useCallback(async (): Promise<void> => {
    if (inFlight.current) {
      again.current = true
      return
    }
    inFlight.current = true
    do {
      again.current = false
      const started = revision.current
      try {
        const [nextOverview, nextList] = await Promise.all([call(() => adminApi.overview()), call(() => adminApi.platforms())])
        setOverview(nextOverview)
        if (revision.current === started) setList(nextList)
        else again.current = true
        setError(null)
      } catch (caught) {
        const problem = toApiError(caught)
        again.current = false
        if (problem.code !== 'not_authenticated') setError(problem)
      }
    } while (again.current)
    inFlight.current = false
  }, [call])

  useEffect(() => {
    const first = window.setTimeout(() => void load(), 0)
    return () => window.clearTimeout(first)
  }, [load])

  // While checks are running the list is refreshed, so results appear as they arrive.
  const checking = list?.platforms.some((platform) => platform.checking) ?? false
  useEffect(() => {
    if (!checking) return
    const id = window.setInterval(() => void load(), POLL_MS)
    return () => window.clearInterval(id)
  }, [checking, load])

  const onPlatform = useCallback(
    (platform: AdminPlatform) => {
      revision.current += 1
      setList((current) => {
        if (!current) return current
        const known = current.platforms.some((item) => item.id === platform.id)
        const platforms = known ? current.platforms.map((item) => (item.id === platform.id ? platform : item)) : [...current.platforms, platform]
        return { ...current, platforms }
      })
      void load() // the counts above depend on it
    },
    [load],
  )

  const onRemoved = useCallback(
    (id: string) => {
      revision.current += 1
      setList((current) => (current ? { ...current, platforms: current.platforms.filter((item) => item.id !== id) } : current))
      void load()
    },
    [load],
  )

  const refresh = async () => {
    setRefreshing(true)
    await load()
    setRefreshing(false)
  }

  const submitPassword = async (current: string, next: string) => {
    await changePassword(current, next)
    setChanging(false)
    setNotice('Your password was changed. Every other device was signed out.')
  }

  return (
    <div className="space-y-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-[clamp(1.6rem,4vw,2.25rem)] font-semibold leading-tight text-ink">Service overview</h1>
          <p className="mt-1.5 truncate text-sm text-ink-soft">
            Signed in as <span className="text-ink">{session.email}</span>
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Button variant="glass" size="sm" loading={refreshing} onClick={() => void refresh()} icon={<RefreshCw className="size-3.5" aria-hidden />}>
            Refresh
          </Button>
          <Button
            variant="glass"
            size="sm"
            aria-expanded={changing}
            onClick={() => {
              setChanging((current) => !current)
              setNotice(null)
            }}
            icon={<KeyRound className="size-3.5" aria-hidden />}
          >
            Change password
          </Button>
        </div>
      </div>

      {notice && (
        <p role="status" className="flex items-start gap-2.5 rounded-2xl border border-ok/30 bg-ok/10 px-4 py-3 text-sm text-ink">
          <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden />
          {notice}
        </p>
      )}

      {changing && (
        <div className="glass mx-auto max-w-xl rounded-3xl p-6 sm:p-8">
          <PasswordForm email={session.email} forced={false} onSubmit={submitPassword} onCancel={() => setChanging(false)} />
        </div>
      )}

      {error && (
        <div role="alert" className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-bad/30 bg-bad/10 px-4 py-3">
          <p className="flex items-start gap-2.5 text-sm text-ink">
            <TriangleAlert className="mt-0.5 size-4 shrink-0 text-bad" aria-hidden />
            <span>
              {error.message}
              {error.hint ? ` ${error.hint}` : ''}
            </span>
          </p>
          <Button variant="glass" size="sm" onClick={() => void refresh()} loading={refreshing}>
            Try again
          </Button>
        </div>
      )}

      {overview ? (
        <Overview overview={overview} now={now} />
      ) : (
        !error && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" role="status" aria-label="Loading the overview">
            {[0, 1, 2, 3].map((index) => (
              <Skeleton key={index} className="h-40" />
            ))}
          </div>
        )
      )}

      {list ? (
        <PlatformManager data={list} now={now} call={call} onPlatform={onPlatform} onRemoved={onRemoved} onReload={load} />
      ) : (
        !error && (
          <div className="space-y-2.5" role="status" aria-label="Loading the platforms">
            {[0, 1, 2, 3, 4].map((index) => (
              <Skeleton key={index} className="h-[4.5rem]" />
            ))}
          </div>
        )
      )}
    </div>
  )
}
