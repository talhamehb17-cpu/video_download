import { Check, Music, Star } from 'lucide-react'
import { useId } from 'react'

import type { Quality } from '../../lib/api'
import { cn } from '../../lib/cn'
import { formatBytes } from '../../lib/format'

interface QualitySelectorProps {
  qualities: Quality[]
  selectedId: string | null
  onSelect: (id: string) => void
  disabled?: boolean
}

function describe(quality: Quality): string {
  const parts: string[] = []
  if (quality.video_codec) parts.push(quality.video_codec)
  if (quality.audio_codec) parts.push(quality.audio_codec)
  if (quality.kind === 'video' && !quality.has_audio) parts.push('no audio')
  if (quality.dynamic_range) parts.push(quality.dynamic_range)
  if (quality.kind === 'audio' && quality.bitrate_kbps) parts.push(`${Math.round(quality.bitrate_kbps)} kbps`)
  return parts.join(' · ')
}

function size(quality: Quality): string {
  if (quality.filesize == null) return 'Size unknown'
  return `${quality.filesize_is_estimate ? '≈ ' : ''}${formatBytes(quality.filesize)}`
}

/** The qualities this source really provides, as a native radio group. */
export function QualitySelector({ qualities, selectedId, onSelect, disabled = false }: QualitySelectorProps) {
  const name = useId()

  return (
    <fieldset disabled={disabled} className="min-w-0">
      <legend className="flex w-full items-center justify-between text-sm font-medium text-ink">
        Quality
        <span className="text-xs font-normal text-ink-mute">
          {qualities.length} option{qualities.length === 1 ? '' : 's'} from the source
        </span>
      </legend>
      <div className="mt-3 grid grid-cols-[repeat(auto-fit,minmax(min(8.75rem,45%),1fr))] gap-2.5">
        {qualities.map((quality) => {
          const selected = quality.id === selectedId
          const blocked = quality.exceeds_limit
          const details = describe(quality)
          return (
            <label
              key={quality.id}
              className={cn(
                'group @container relative flex min-h-[104px] min-w-0 flex-col rounded-2xl border p-3 text-left transition-[border-color,background-color,box-shadow,transform] duration-200',
                'has-focus-visible:outline-2 has-focus-visible:outline-offset-2 has-focus-visible:outline-cyan',
                blocked
                  ? 'cursor-not-allowed border-line bg-transparent opacity-50'
                  : selected
                    ? 'border-violet/70 bg-violet/12 shadow-[0_0_0_1px_color-mix(in_oklab,var(--violet)_45%,transparent),0_10px_30px_-12px_color-mix(in_oklab,var(--violet)_70%,transparent)]'
                    : 'cursor-pointer border-line bg-glass hover:-translate-y-0.5 hover:border-line-strong hover:bg-glass-strong',
              )}
            >
              <input
                type="radio"
                name={name}
                value={quality.id}
                checked={selected}
                disabled={blocked}
                onChange={() => onSelect(quality.id)}
                className="sr-only"
              />
              <span className="flex items-start justify-between gap-2">
                <span className="flex min-w-0 items-center gap-1.5 font-display text-[17px] font-semibold tracking-tight text-ink">
                  {quality.kind === 'audio' && <Music className="size-4 shrink-0 text-cyan" aria-hidden />}
                  <span className="truncate">{quality.label}</span>
                </span>
                <span
                  aria-hidden
                  className={cn(
                    'grid size-5 shrink-0 place-items-center rounded-full border transition-colors',
                    selected ? 'border-transparent bg-brand text-white' : 'border-line-strong text-transparent',
                  )}
                >
                  <Check className="size-3" strokeWidth={3} />
                </span>
              </span>
              {/* format first, so the badges line up across cards; size sits on the bottom edge */}
              <span className="mt-2 flex min-w-0 flex-wrap items-center gap-1.5">
                <span className="rounded-md border border-line bg-glass px-1.5 py-0.5 font-mono text-[10.5px] uppercase tracking-wide text-ink-soft">
                  {quality.container}
                </span>
                {quality.recommended && !blocked && (
                  <span className="inline-flex max-w-full items-center gap-1 rounded-md bg-cyan/12 px-1.5 py-0.5 text-[10.5px] font-medium text-cyan">
                    <Star className="size-2.5 shrink-0 fill-current" aria-hidden />
                    {/* the full word where the card has room for it, a shorter one where it does not */}
                    <span className="@[7rem]:hidden">Top pick</span>
                    <span className="hidden @[7rem]:inline">Recommended</span>
                  </span>
                )}
              </span>
              <span className="mt-auto block min-w-0 pt-2 text-xs text-ink-mute">
                {blocked ? (
                  'Over the size limit'
                ) : (
                  <>
                    <span className="block truncate">{size(quality)}</span>
                    {details && (
                      <span className="mt-0.5 block truncate text-[11px]" title={details}>
                        {details}
                      </span>
                    )}
                  </>
                )}
              </span>
            </label>
          )
        })}
      </div>
    </fieldset>
  )
}
