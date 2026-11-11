import { ScanSearch } from 'lucide-react'

import { useElapsed } from '../../hooks/useCountdown'
import { hostnameOf } from '../../lib/format'
import { Button } from '../ui/Button'

interface AnalyzingCardProps {
  url: string
  startedAt: number
  onCancel: () => void
}

/** Shown while the server checks the link. The timer is real elapsed time. */
export function AnalyzingCard({ url, startedAt, onCancel }: AnalyzingCardProps) {
  const elapsed = useElapsed(startedAt)
  const host = hostnameOf(url)

  return (
    <div className="glass rounded-3xl p-5 text-left sm:p-6">
      <div className="flex flex-col gap-5 sm:flex-row sm:items-center">
        <div className="relative aspect-video w-full shrink-0 overflow-hidden rounded-2xl border border-line bg-glass sm:w-64">
          <div className="absolute inset-0 grid place-items-center">
            <ScanSearch className="size-9 text-ink-mute" aria-hidden />
          </div>
          <div aria-hidden className="absolute inset-x-0 top-0 h-full animate-scan">
            <div className="h-16 bg-linear-to-b from-transparent via-cyan/25 to-transparent" />
            <div className="h-px bg-cyan/80 shadow-[0_0_18px_2px_color-mix(in_oklab,var(--cyan)_70%,transparent)]" />
          </div>
        </div>

        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium uppercase tracking-[0.16em] text-cyan">Analyzing</p>
          <p className="mt-1.5 truncate font-display text-xl font-semibold tracking-tight text-ink">
            {host ? `Reading ${host}` : 'Reading the link'}
          </p>
          <p className="mt-1.5 text-sm text-ink-soft">
            Checking the link and finding the qualities and subtitles this source offers.
          </p>
          <div aria-hidden className="mt-4 space-y-2.5">
            <div className="h-2.5 w-4/5 animate-pulse rounded-full bg-glass-strong" />
            <div className="h-2.5 w-3/5 animate-pulse rounded-full bg-glass-strong [animation-delay:150ms]" />
          </div>
          <div className="mt-5 flex items-center justify-between gap-3">
            <span className="font-mono text-xs tabular-nums text-ink-mute">{elapsed}s elapsed</span>
            <Button variant="glass" size="sm" onClick={onCancel}>
              Cancel
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
