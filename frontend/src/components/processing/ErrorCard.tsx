import { m } from 'framer-motion'
import { Ban, HardDrive, Hourglass, Link2Off, Lock, Radio, RotateCcw, Scale, ShieldAlert, TriangleAlert, Unplug, type LucideIcon } from 'lucide-react'
import { useState, type ReactNode } from 'react'

import { useCountdown } from '../../hooks/useCountdown'
import type { ApiError } from '../../lib/api'
import { Button } from '../ui/Button'

const ICONS: Record<string, LucideIcon> = {
  invalid_url: Link2Off,
  unsupported_scheme: Link2Off,
  unsupported_source: Link2Off,
  not_found: Link2Off,
  blocked_destination: ShieldAlert,
  domain_not_allowed: ShieldAlert,
  platform_disabled: Ban,
  platform_unsupported: Lock,
  file_too_large: Scale,
  too_long: Scale,
  insufficient_storage: HardDrive,
  storage_full: HardDrive,
  private_content: Lock,
  login_required: Lock,
  paywalled: Lock,
  age_restricted: Lock,
  age_rating_blocked: Lock,
  geo_restricted: Lock,
  drm_protected: Lock,
  verification_required: Lock,
  live_stream: Radio,
  rate_limited: Hourglass,
  server_busy: Hourglass,
  too_many_jobs: Hourglass,
  network_error: Unplug,
  service_unavailable: Unplug,
  not_configured: Unplug,
  source_unreachable: Unplug,
  source_timeout: Unplug,
}

interface ErrorCardProps {
  error: ApiError
  /** What was being attempted, e.g. the link. */
  subject?: string
  /** Something this page knows that helps with the error, shown after the server's hint. */
  note?: ReactNode
  onRetry?: () => void
  onDismiss?: () => void
  retryLabel?: string
  dismissLabel?: string
}

/** A failure, explained in the server's own words (code-specific message and hint). */
export function ErrorCard({ error, subject, note, onRetry, onDismiss, retryLabel = 'Try again', dismissLabel = 'Use another link' }: ErrorCardProps) {
  const Icon = ICONS[error.code] ?? TriangleAlert
  // When the server says how long to wait, hold the retry button until then. The
  // deadline is fixed when the error first appears, not recomputed on each render.
  const [waitUntil] = useState(() => (error.retryAfter ? Date.now() + error.retryAfter * 1000 : null))
  const remaining = useCountdown(waitUntil)
  const waiting = remaining !== null && remaining > 0

  return (
    <div role="alert" className="glass rounded-3xl border-bad/25 p-5 text-left sm:p-6">
      <div className="flex gap-4">
        {/* One short shake draws the eye to what went wrong, then everything is still. */}
        <m.div
          initial={{ scale: 0.6, opacity: 0 }}
          animate={{ scale: 1, opacity: 1, x: [0, -5, 5, -3, 3, 0] }}
          transition={{ duration: 0.5, ease: 'easeOut' }}
          className="grid size-11 shrink-0 place-items-center rounded-2xl border border-bad/30 bg-bad/10 text-bad"
        >
          <Icon className="size-5" aria-hidden />
        </m.div>
        <div className="min-w-0 flex-1">
          <p className="font-display text-lg font-semibold tracking-tight text-ink">{error.message}</p>
          {error.hint && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{error.hint}</p>}
          {note && <p className="mt-1 text-sm leading-relaxed text-ink-soft">{note}</p>}
          {subject && <p className="mt-2 truncate font-mono text-xs text-ink-mute">{subject}</p>}
          {(onRetry || onDismiss) && (
            <div className="mt-4 flex flex-wrap gap-2">
              {onRetry && (
                <Button variant="glass" size="sm" onClick={onRetry} disabled={waiting} icon={<RotateCcw className="size-3.5" aria-hidden />}>
                  {waiting ? `${retryLabel} in ${Math.ceil(remaining)}s` : retryLabel}
                </Button>
              )}
              {onDismiss && (
                <Button variant="quiet" size="sm" onClick={onDismiss}>
                  {dismissLabel}
                </Button>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
