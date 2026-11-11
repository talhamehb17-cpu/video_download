import { m } from 'framer-motion'
import { ArrowDownToLine, Ban, Captions, CircleCheck, Hourglass, Info, ListRestart, Timer, Trash2, WifiOff } from 'lucide-react'

import { useCountdown } from '../../hooks/useCountdown'
import { isActive } from '../../hooks/useDownloader'
import { ApiError, apiUrl, type Analysis, type Job } from '../../lib/api'
import { cn } from '../../lib/cn'
import { formatBytes, formatClock, formatEta, formatSpeed, languageName } from '../../lib/format'
import { Button } from '../ui/Button'
import { buttonClass } from '../ui/buttonClass'
import { ErrorCard } from './ErrorCard'
import { Poster } from './ResultCard'

interface JobPanelProps {
  analysis: Analysis
  job: Job
  expiresAt: number | null
  busy: boolean
  reconnecting: boolean
  onCancel: () => void
  onBack: () => void
  onReset: () => void
}

const PROCESSING_TEXT: Record<string, string> = {
  merging: 'Merging video and audio',
  embedding_subtitles: 'Embedding subtitles',
  converting_subtitles: 'Converting subtitles',
  optimizing: 'Finalizing the file',
}

/** What the server is doing right now, in plain words. */
function statusText(job: Job): string {
  if (job.status === 'queued') {
    return job.queue_position && job.queue_position > 1 ? `Waiting in line (position ${job.queue_position})` : 'Waiting for a free slot'
  }
  if (job.stage === 'downloading') {
    const { part, parts, part_kind: kind } = job.progress
    const what = kind === 'video' ? 'Downloading video' : kind === 'audio' ? 'Downloading audio' : 'Downloading'
    return parts && parts > 1 && part ? `${what} (part ${part} of ${parts})` : what
  }
  if (job.stage === 'processing') return PROCESSING_TEXT[job.stage_detail ?? ''] ?? 'Processing the file'
  return 'Starting'
}

function ProgressBar({ percent, label }: { percent: number | null; label: string }) {
  const known = percent !== null
  return (
    <div
      role="progressbar"
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-valuenow={known ? Math.round(percent) : undefined}
      aria-valuetext={known ? `${Math.round(percent)} percent` : label}
      className="relative h-2.5 overflow-hidden rounded-full bg-glass-strong"
    >
      {known ? (
        <m.div
          className="bg-brand relative h-full overflow-hidden rounded-full shadow-[0_0_18px_color-mix(in_oklab,var(--violet)_70%,transparent)]"
          initial={false}
          animate={{ width: `${Math.max(1.5, Math.min(100, percent))}%` }}
          transition={{ type: 'spring', stiffness: 90, damping: 22, mass: 0.6 }}
        >
          <span aria-hidden className="absolute inset-y-0 left-0 w-1/3 animate-sheen bg-linear-to-r from-transparent via-white/45 to-transparent" />
        </m.div>
      ) : (
        // No measurable progress for this step: show activity, not a made-up number.
        <span aria-hidden className="bg-brand absolute inset-y-0 left-0 w-2/5 origin-left animate-indeterminate rounded-full" />
      )}
    </div>
  )
}

function Header({ analysis, job }: { analysis: Analysis; job: Job }) {
  return (
    <div className="flex items-center gap-4">
      <div className="hidden w-36 shrink-0 sm:block">
        <Poster analysis={analysis} />
      </div>
      <div className="min-w-0">
        <p className="line-clamp-2 font-display text-lg font-semibold leading-snug tracking-tight text-ink">{job.title}</p>
        <p className="mt-1 text-sm text-ink-mute">
          {job.quality_label} · <span className="uppercase">{job.container}</span> · {analysis.source.domain}
        </p>
      </div>
    </div>
  )
}

function ActiveJob({ job, busy, reconnecting, onCancel }: Pick<JobPanelProps, 'job' | 'busy' | 'reconnecting' | 'onCancel'>) {
  const { progress } = job
  const downloading = job.stage === 'downloading'
  const percent = downloading ? progress.percent : null
  const status = statusText(job)

  const stats: string[] = []
  if (downloading && progress.downloaded_bytes > 0) {
    stats.push(
      progress.total_bytes
        ? `${formatBytes(progress.downloaded_bytes)} of ${formatBytes(progress.total_bytes)}`
        : `${formatBytes(progress.downloaded_bytes)} so far`,
    )
    const speed = formatSpeed(progress.speed_bps)
    if (speed) stats.push(speed)
    const eta = formatEta(progress.eta_seconds)
    if (eta) stats.push(eta)
  }

  return (
    <div className="mt-6">
      <div className="mb-2.5 flex items-baseline justify-between gap-3">
        <p className="flex min-w-0 items-center gap-2 text-sm font-medium text-ink" aria-live="polite">
          {job.status === 'queued' && <Hourglass className="size-4 shrink-0 text-warn" aria-hidden />}
          <span className="truncate">{status}…</span>
        </p>
        {percent !== null && <span className="font-mono text-sm tabular-nums text-ink">{percent.toFixed(percent >= 10 ? 0 : 1)}%</span>}
      </div>
      <ProgressBar percent={percent} label={status} />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-3">
        <p className="min-h-5 font-mono text-xs tabular-nums text-ink-mute">
          {reconnecting ? (
            <span className="inline-flex items-center gap-1.5 text-warn">
              <WifiOff className="size-3.5" aria-hidden />
              Connection lost. Reconnecting; your download continues on the server.
            </span>
          ) : (
            stats.join(' · ')
          )}
        </p>
        <Button variant="danger" size="sm" onClick={onCancel} loading={busy} icon={<Ban className="size-3.5" aria-hidden />}>
          Cancel
        </Button>
      </div>
    </div>
  )
}

function ReadyJob({ job, expiresAt, busy, onCancel, onBack }: Pick<JobPanelProps, 'job' | 'expiresAt' | 'busy' | 'onCancel' | 'onBack'>) {
  const remaining = useCountdown(expiresAt)
  const file = job.file
  if (!file) return null
  const expired = remaining !== null && remaining <= 0

  return (
    <m.div initial={{ opacity: 0, y: 10 }} animate={{ opacity: 1, y: 0 }} transition={{ duration: 0.4 }} className="mt-6">
      <div className="rounded-2xl border border-ok/30 bg-ok/8 p-4 sm:p-5">
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <m.span
              initial={{ scale: 0.4, opacity: 0 }}
              animate={{ scale: 1, opacity: 1 }}
              transition={{ type: 'spring', stiffness: 380, damping: 18, delay: 0.1 }}
              className="mt-0.5 shrink-0 text-ok"
            >
              <CircleCheck className="size-6" aria-hidden />
            </m.span>
            <div className="min-w-0">
              <p className="font-display text-lg font-semibold tracking-tight text-ink">Your file is ready</p>
              <p className="mt-0.5 break-words text-sm text-ink-soft">{file.name}</p>
              <p className="mt-1 font-mono text-xs text-ink-mute">
                {formatBytes(file.size)} · <span className="uppercase">{file.container}</span>
              </p>
            </div>
          </div>
          {/* A plain link to the file: the browser streams it straight to disk. */}
          <a
            href={expired ? undefined : apiUrl(file.url)}
            download={file.name}
            aria-disabled={expired || undefined}
            className={cn(buttonClass('primary', 'lg', 'w-full shrink-0 sm:w-auto'), expired && 'pointer-events-none opacity-50')}
          >
            <ArrowDownToLine className="size-4" aria-hidden />
            Save file
          </a>
        </div>
      </div>

      {job.embedded_subtitles.length > 0 && (
        <p className="mt-3 flex items-start gap-2 text-sm text-ink-soft">
          <Captions className="mt-0.5 size-4 shrink-0 text-blue" aria-hidden />
          Subtitles embedded: {job.embedded_subtitles.map((code) => languageName(code)).join(', ')}
        </p>
      )}
      {job.notices.map((notice) => (
        <p key={notice.code} className="mt-3 flex items-start gap-2 text-sm text-ink-soft">
          <Info className="mt-0.5 size-4 shrink-0 text-warn" aria-hidden />
          {notice.message}
        </p>
      ))}

      <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
        <p className="inline-flex items-center gap-2 text-sm text-ink-mute" aria-live="off">
          <Timer className="size-4" aria-hidden />
          {remaining === null || expired ? (
            'This file is being deleted from the server.'
          ) : (
            <>
              Deleted from the server in <span className="font-mono tabular-nums text-ink-soft">{formatClock(remaining)}</span>
            </>
          )}
        </p>
        <div className="flex flex-wrap gap-2">
          <Button variant="glass" size="sm" onClick={onBack} icon={<ListRestart className="size-3.5" aria-hidden />}>
            Other qualities
          </Button>
          <Button variant="danger" size="sm" onClick={onCancel} loading={busy} icon={<Trash2 className="size-3.5" aria-hidden />}>
            Delete now
          </Button>
        </div>
      </div>
    </m.div>
  )
}

const ENDED_TEXT: Partial<Record<Job['status'], { title: string; text: string }>> = {
  cancelled: { title: 'Download cancelled', text: 'The transfer was stopped and nothing was kept on the server.' },
  expired: { title: 'This file has been deleted', text: 'It reached its time limit on the server. You can prepare it again.' },
  deleted: { title: 'File deleted', text: 'The file was removed from the server right away, as you asked.' },
}

export function JobPanel({ analysis, job, expiresAt, busy, reconnecting, onCancel, onBack, onReset }: JobPanelProps) {
  const ended = ENDED_TEXT[job.status]

  return (
    <div className="glass rounded-3xl p-4 text-left sm:p-6">
      <Header analysis={analysis} job={job} />

      {isActive(job) && <ActiveJob job={job} busy={busy} reconnecting={reconnecting} onCancel={onCancel} />}

      {job.status === 'completed' && <ReadyJob job={job} expiresAt={expiresAt} busy={busy} onCancel={onCancel} onBack={onBack} />}

      {job.status === 'failed' && (
        <div className="mt-6">
          <ErrorCard
            error={new ApiError(job.error?.code ?? 'download_failed', job.error?.message ?? 'The download failed.', { hint: job.error?.hint })}
            onRetry={onBack}
            onDismiss={onReset}
            retryLabel="Back to options"
          />
        </div>
      )}

      {ended && (
        <div className="mt-6 flex flex-col gap-4 rounded-2xl border border-line bg-glass p-4 sm:flex-row sm:items-center sm:justify-between sm:p-5">
          <div>
            <p className="font-display text-lg font-semibold tracking-tight text-ink">{ended.title}</p>
            <p className="mt-0.5 text-sm text-ink-soft">{ended.text}</p>
          </div>
          <div className="flex flex-wrap gap-2">
            <Button variant="glass" size="sm" onClick={onBack} icon={<ListRestart className="size-3.5" aria-hidden />}>
              Back to options
            </Button>
            <Button variant="quiet" size="sm" onClick={onReset}>
              Use another link
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}
