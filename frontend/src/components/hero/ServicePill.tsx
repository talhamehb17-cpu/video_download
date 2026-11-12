import { LoaderCircle, RotateCcw } from 'lucide-react'

import type { ServiceState } from '../../hooks/useServiceStatus'
import { cn } from '../../lib/cn'
import { usable } from '../../lib/platforms'

interface ServicePillProps {
  state: ServiceState
  onRetry: () => void
}

/** Live status of the download service, straight from its health/config endpoint. */
export function ServicePill({ state, onRetry }: ServicePillProps) {
  let dot = 'bg-ink-mute'
  let text: string
  let spinning = false
  let canRetry = false

  switch (state.status) {
    case 'checking':
      text = 'Connecting to the download service…'
      spinning = true
      break
    case 'waking':
      text = 'Waking up the server. This can take up to a minute…'
      spinning = true
      break
    case 'online': {
      const { sources } = state.config
      const count = usable(state.platforms).length
      dot = 'bg-ok shadow-[0_0_10px_2px_color-mix(in_oklab,var(--ok)_55%,transparent)]'
      if (sources.mode === 'allowlist')
        text = `Service online · ${sources.domains.length} trusted source${sources.domains.length === 1 ? '' : 's'} enabled`
      else if (count > 0) text = `Service online · ${count} platform${count === 1 ? '' : 's'} enabled`
      else text = 'Service online'
      break
    }
    case 'offline':
      dot = state.reason === 'not_configured' ? 'bg-warn' : 'bg-bad'
      text = state.reason === 'not_configured' ? 'Download service not connected yet' : 'Download service unreachable'
      canRetry = state.reason === 'unreachable'
      break
  }

  return (
    <div
      role="status"
      aria-live="polite"
      className="inline-flex max-w-full items-center gap-2.5 rounded-full border border-line bg-glass py-1.5 pl-3 pr-3.5 text-[13px] text-ink-soft backdrop-blur-md"
    >
      {spinning ? (
        <LoaderCircle className="size-3.5 shrink-0 animate-spin text-cyan" aria-hidden />
      ) : (
        <span aria-hidden className={cn('size-2 shrink-0 rounded-full', dot)} />
      )}
      <span className="truncate">{text}</span>
      {canRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="-mr-1.5 ml-0.5 inline-flex items-center gap-1 rounded-full border border-line px-2 py-0.5 text-xs text-ink hover:border-line-strong"
        >
          <RotateCcw className="size-3" aria-hidden />
          Retry
        </button>
      )}
    </div>
  )
}
