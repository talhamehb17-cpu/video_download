import { useEffect, useState } from 'react'

/** Current time, refreshed every second while `active`. */
function useNow(active: boolean): number {
  const [now, setNow] = useState(() => Date.now())

  useEffect(() => {
    if (!active) return
    const tick = () => setNow(Date.now())
    const first = window.setTimeout(tick, 0) // catch up at once after a period of inactivity
    const id = window.setInterval(tick, 1000)
    return () => {
      window.clearTimeout(first)
      window.clearInterval(id)
    }
  }, [active])

  return now
}

/** Seconds left until `deadline` (a `Date.now()` timestamp), updated every second. */
export function useCountdown(deadline: number | null): number | null {
  const now = useNow(deadline !== null)
  return deadline === null ? null : Math.max(0, (deadline - now) / 1000)
}

/** Whole seconds elapsed since `since` (a `Date.now()` timestamp). */
export function useElapsed(since: number | null): number {
  const now = useNow(since !== null)
  return since === null ? 0 : Math.max(0, Math.floor((now - since) / 1000))
}

/** The current time (`Date.now()`), refreshed every `everyMs`: for "5 min ago" style texts. */
export function useClock(everyMs = 30_000): number {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), everyMs)
    return () => window.clearInterval(id)
  }, [everyMs])
  return now
}
