import { Captions, Check, Download, LoaderCircle, Search } from 'lucide-react'
import { useMemo, useState } from 'react'

import { api, saveBlob, toApiError, type SubtitleFormat, type SubtitleTrack } from '../../lib/api'
import { cn } from '../../lib/cn'
import { languageName } from '../../lib/format'

interface SubtitlePanelProps {
  analysisId: string
  tracks: SubtitleTrack[]
  /** Whether the selected quality can carry embedded subtitles. */
  canEmbed: boolean
  embedIds: string[]
  onToggleEmbed: (id: string) => void
  disabled?: boolean
}

type DownloadState = 'loading' | 'done'

const FILTER_THRESHOLD = 8

export function SubtitlePanel({ analysisId, tracks, canEmbed, embedIds, onToggleEmbed, disabled = false }: SubtitlePanelProps) {
  const [states, setStates] = useState<Record<string, DownloadState | undefined>>({})
  const [errors, setErrors] = useState<Record<string, string | undefined>>({})
  const [query, setQuery] = useState('')

  const named = useMemo(
    () => tracks.map((track) => ({ track, name: languageName(track.language, track.name) })),
    [tracks],
  )
  const visible = useMemo(() => {
    const needle = query.trim().toLowerCase()
    if (!needle) return named
    return named.filter(({ track, name }) => name.toLowerCase().includes(needle) || track.language.toLowerCase().includes(needle))
  }, [named, query])

  const download = async (track: SubtitleTrack, format: SubtitleFormat) => {
    const key = `${track.id}.${format}`
    if (states[key] === 'loading') return
    setStates((current) => ({ ...current, [key]: 'loading' }))
    setErrors((current) => ({ ...current, [track.id]: undefined }))
    try {
      const { blob, filename } = await api.subtitle(analysisId, track.id, format)
      saveBlob(blob, filename)
      setStates((current) => ({ ...current, [key]: 'done' }))
      window.setTimeout(() => setStates((current) => ({ ...current, [key]: undefined })), 2500)
    } catch (error) {
      const apiError = toApiError(error)
      setStates((current) => ({ ...current, [key]: undefined }))
      setErrors((current) => ({ ...current, [track.id]: [apiError.message, apiError.hint].filter(Boolean).join(' ') }))
    }
  }

  return (
    <section aria-labelledby="subtitles-heading" className="min-w-0">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h3 id="subtitles-heading" className="flex items-center gap-2 font-sans text-sm font-medium tracking-normal text-ink">
          <Captions className="size-4 text-blue" aria-hidden />
          Subtitles
        </h3>
        <span className="text-xs text-ink-mute">
          {tracks.length === 0 ? 'None published by the source' : `${tracks.length} language${tracks.length === 1 ? '' : 's'} found`}
        </span>
      </div>

      {tracks.length === 0 ? (
        <p className="mt-3 rounded-2xl border border-dashed border-line px-4 py-5 text-sm text-ink-mute">
          This video has no subtitle tracks at the source, so there is nothing to download or embed.
        </p>
      ) : (
        <>
          {tracks.length > FILTER_THRESHOLD && (
            <label className="mt-3 flex items-center gap-2 rounded-xl border border-line bg-glass px-3">
              <Search className="size-4 text-ink-mute" aria-hidden />
              <span className="sr-only">Filter languages</span>
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="Filter languages…"
                className="h-10 min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-mute"
              />
            </label>
          )}

          <ul className="thin-scrollbar mt-3 max-h-[21rem] divide-y divide-line overflow-y-auto rounded-2xl border border-line bg-glass">
            {visible.map(({ track, name }) => {
              const embedded = embedIds.includes(track.id)
              const error = errors[track.id]
              return (
                <li key={track.id} className="px-3.5 py-2.5">
                  {/* one line where there is room; otherwise the name, then the actions */}
                  <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
                    <div className="min-w-0 flex-1 basis-24">
                      {/* long names wrap rather than lose their ending: "Spanish" and "Latin American Spanish" differ there */}
                      <p className="text-sm font-medium leading-snug text-ink [overflow-wrap:anywhere]">
                        {name}
                        {/* the code is only worth showing when it is not already the name */}
                        {name !== track.language && (
                          <span className="ml-2 whitespace-nowrap font-mono text-xs font-normal text-ink-mute">{track.language}</span>
                        )}
                      </p>
                      {track.kind === 'auto' && (
                        <p className="mt-1">
                          <span className="rounded bg-warn/12 px-1.5 py-px text-[10.5px] font-medium text-warn">Auto-generated</span>
                        </p>
                      )}
                    </div>

                    <div className="flex items-center gap-1.5">
                      {track.formats.map((format) => {
                        const state = states[`${track.id}.${format}`]
                        return (
                          <button
                            key={format}
                            type="button"
                            disabled={state === 'loading'}
                            onClick={() => void download(track, format)}
                            aria-label={`Download ${name} subtitles as ${format.toUpperCase()}`}
                            className={cn(
                              'inline-flex h-9 items-center gap-1.5 rounded-full border px-3 text-xs font-medium uppercase tracking-wide transition-colors sm:h-8',
                              state === 'done'
                                ? 'border-ok/40 bg-ok/10 text-ok'
                                : 'border-line bg-glass text-ink-soft hover:border-line-strong hover:bg-glass-strong hover:text-ink',
                            )}
                          >
                            {state === 'loading' ? (
                              <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
                            ) : state === 'done' ? (
                              <Check className="size-3.5" aria-hidden />
                            ) : (
                              <Download className="size-3.5" aria-hidden />
                            )}
                            {format}
                          </button>
                        )
                      })}

                      {track.embeddable && (
                        <label
                          className={cn(
                            'ml-1 inline-flex min-h-9 items-center gap-2 text-xs sm:min-h-8',
                            canEmbed && !disabled ? 'cursor-pointer text-ink-soft' : 'cursor-not-allowed text-ink-mute opacity-60',
                          )}
                          title={canEmbed ? 'Add this track inside the video file' : 'The selected format cannot hold subtitles'}
                        >
                          <input
                            type="checkbox"
                            className="peer sr-only"
                            checked={embedded && canEmbed}
                            disabled={!canEmbed || disabled}
                            onChange={() => onToggleEmbed(track.id)}
                          />
                          <span
                            aria-hidden
                            className="relative h-5 w-9 shrink-0 rounded-full border border-line-strong bg-glass transition-colors peer-checked:border-transparent peer-checked:bg-brand peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-cyan after:absolute after:left-0.5 after:top-1/2 after:size-3.5 after:-translate-y-1/2 after:rounded-full after:bg-ink-soft after:transition-transform peer-checked:after:translate-x-4 peer-checked:after:bg-white"
                          />
                          Embed
                        </label>
                      )}
                    </div>
                  </div>
                  {error && (
                    <p role="alert" className="mt-2 text-xs text-bad">
                      {error}
                    </p>
                  )}
                </li>
              )
            })}
            {visible.length === 0 && <li className="px-4 py-5 text-sm text-ink-mute">No language matches “{query}”.</li>}
          </ul>

          <p className="mt-2.5 text-xs leading-relaxed text-ink-mute">
            {canEmbed
              ? 'Download a track on its own, or switch on Embed to include it inside the video file.'
              : 'Each track downloads as its own file. The selected format cannot hold embedded subtitles.'}
          </p>
        </>
      )}
    </section>
  )
}
