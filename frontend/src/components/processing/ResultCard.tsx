import { ArrowDownToLine, Clock, Globe, ImageOff, Info, User, X } from 'lucide-react'
import { useState } from 'react'

import { apiUrl, type Analysis, type ApiError, type Quality } from '../../lib/api'
import { formatBytes, formatDuration } from '../../lib/format'
import { Button } from '../ui/Button'
import { QualitySelector } from './QualitySelector'
import { SubtitlePanel } from './SubtitlePanel'

interface ResultCardProps {
  analysis: Analysis
  selected: Quality | null
  embedIds: string[]
  starting: boolean
  startError: ApiError | null
  onSelectQuality: (id: string) => void
  onToggleEmbed: (id: string) => void
  onStart: () => void
  onReset: () => void
}

/** Poster with a fixed 16:9 box, so nothing shifts when the image arrives (or fails). */
export function Poster({ analysis }: { analysis: Analysis }) {
  const [failed, setFailed] = useState(false)
  const duration = formatDuration(analysis.duration)
  return (
    <div className="relative aspect-video w-full overflow-hidden rounded-2xl border border-line bg-bg-soft">
      {analysis.thumbnail_url && !failed ? (
        <img
          src={apiUrl(analysis.thumbnail_url)}
          alt=""
          width={640}
          height={360}
          loading="lazy"
          decoding="async"
          onError={() => setFailed(true)}
          className="size-full object-cover"
        />
      ) : (
        <div className="grid size-full place-items-center bg-[radial-gradient(circle_at_30%_20%,color-mix(in_oklab,var(--violet)_22%,transparent),transparent_60%)]">
          <ImageOff className="size-7 text-ink-mute" aria-hidden />
          <span className="sr-only">No preview image available</span>
        </div>
      )}
      {duration && (
        <span className="absolute bottom-2 right-2 inline-flex items-center gap-1 rounded-md bg-black/70 px-1.5 py-0.5 font-mono text-[11px] text-white backdrop-blur-sm">
          <Clock className="size-3" aria-hidden />
          <span className="sr-only">Duration </span>
          {duration}
        </span>
      )}
    </div>
  )
}

export function ResultCard({
  analysis,
  selected,
  embedIds,
  starting,
  startError,
  onSelectQuality,
  onToggleEmbed,
  onStart,
  onReset,
}: ResultCardProps) {
  const canEmbed = selected?.can_embed_subtitles ?? false
  const embedCount = canEmbed ? embedIds.length : 0

  const summary: string[] = []
  if (selected) {
    summary.push(`${selected.label} ${selected.container.toUpperCase()}`)
    if (selected.filesize != null) summary.push(`${selected.filesize_is_estimate ? '≈ ' : ''}${formatBytes(selected.filesize)}`)
    if (selected.requires_merge) summary.push('video + audio merged for you')
    if (embedCount > 0) summary.push(`${embedCount} subtitle track${embedCount === 1 ? '' : 's'} embedded`)
  }

  return (
    <div className="glass rounded-3xl p-4 text-left sm:p-6">
      <div className="flex flex-col gap-5 md:flex-row">
        <div className="w-full shrink-0 md:w-72">
          <Poster analysis={analysis} />
        </div>
        <div className="min-w-0 flex-1">
          <div className="flex items-start justify-between gap-3">
            <h2 className="line-clamp-3 font-display text-xl font-semibold leading-snug tracking-tight text-ink sm:text-2xl">
              {analysis.title}
            </h2>
            <button
              type="button"
              onClick={onReset}
              aria-label="Close and start over"
              className="-mr-1 -mt-1 grid size-9 shrink-0 place-items-center rounded-full text-ink-mute transition-colors hover:bg-glass-strong hover:text-ink"
            >
              <X className="size-4" aria-hidden />
            </button>
          </div>
          <ul className="mt-3 flex flex-wrap gap-x-4 gap-y-1.5 text-sm text-ink-soft">
            {analysis.uploader && (
              <li className="inline-flex min-w-0 items-center gap-1.5">
                <User className="size-3.5 shrink-0 text-ink-mute" aria-hidden />
                <span className="truncate">{analysis.uploader}</span>
              </li>
            )}
            <li className="inline-flex items-center gap-1.5">
              <Globe className="size-3.5 text-ink-mute" aria-hidden />
              {analysis.source.domain}
            </li>
            {analysis.duration != null && (
              <li className="inline-flex items-center gap-1.5">
                <Clock className="size-3.5 text-ink-mute" aria-hidden />
                {formatDuration(analysis.duration)}
              </li>
            )}
          </ul>
          {analysis.notices.map((notice) => (
            <p key={notice.code} className="mt-3 flex gap-2 rounded-xl border border-blue/25 bg-blue/8 px-3 py-2 text-[13px] text-ink-soft">
              <Info className="mt-0.5 size-3.5 shrink-0 text-blue" aria-hidden />
              {notice.message}
            </p>
          ))}
        </div>
      </div>

      <div className="mt-6 grid gap-6 lg:grid-cols-[1.25fr_1fr]">
        <QualitySelector qualities={analysis.qualities} selectedId={selected?.id ?? null} onSelect={onSelectQuality} disabled={starting} />
        <SubtitlePanel
          analysisId={analysis.id}
          tracks={analysis.subtitles}
          canEmbed={canEmbed}
          embedIds={embedIds}
          onToggleEmbed={onToggleEmbed}
          disabled={starting}
        />
      </div>

      {startError && (
        <p role="alert" className="mt-5 rounded-xl border border-bad/30 bg-bad/10 px-4 py-3 text-sm text-ink">
          <span className="font-medium">{startError.message}</span>
          {startError.hint && <span className="text-ink-soft"> {startError.hint}</span>}
        </p>
      )}

      <div className="mt-6 flex flex-col gap-3 border-t border-line pt-5 sm:flex-row sm:items-center sm:justify-between">
        <p className="min-w-0 text-sm text-ink-soft" aria-live="polite">
          {selected ? summary.join(' · ') : 'Every option from this source is over this service’s size limit.'}
        </p>
        <Button
          size="lg"
          onClick={onStart}
          loading={starting}
          disabled={!selected}
          icon={<ArrowDownToLine className="size-4" aria-hidden />}
          className="w-full shrink-0 sm:w-auto"
        >
          {starting ? 'Starting' : 'Download'}
        </Button>
      </div>
    </div>
  )
}
