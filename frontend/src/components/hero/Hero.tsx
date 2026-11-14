import { m } from 'framer-motion'
import { BadgeCheck, Captions, Timer } from 'lucide-react'
import type { ReactNode, RefObject } from 'react'

import type { ServiceState } from '../../hooks/useServiceStatus'
import { formatSpan } from '../../lib/format'
import { Link } from '../../lib/Link'
import { detect, featured, namesPlatforms, summarise } from '../../lib/platforms'
import { listSources } from '../../lib/site'
import { ServicePill } from './ServicePill'
import { UrlForm } from './UrlForm'

interface HeroProps {
  service: ServiceState
  onRetryService: () => void
  url: string
  onUrlChange: (value: string) => void
  onSubmit: (url: string) => void
  busy: boolean
  inputRef: RefObject<HTMLInputElement | null>
  children?: ReactNode
}

const EASE = [0.16, 1, 0.3, 1] as const

function Word({ children, index }: { children: string; index: number }) {
  return (
    <span className="inline-block overflow-hidden pb-[0.12em] align-bottom">
      <m.span
        className="inline-block"
        initial={{ y: '105%', opacity: 0, filter: 'blur(10px)' }}
        animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
        transition={{ duration: 0.9, delay: 0.12 + index * 0.09, ease: EASE }}
      >
        {children}
      </m.span>
    </span>
  )
}

function fade(delay: number) {
  return {
    initial: { opacity: 0, y: 18 },
    animate: { opacity: 1, y: 0 },
    transition: { duration: 0.8, delay, ease: EASE },
  }
}

export function Hero({ service, onRetryService, url, onUrlChange, onSubmit, busy, inputRef, children }: HeroProps) {
  const config = service.status === 'online' ? service.config : null
  const platforms = service.status === 'online' ? service.platforms : null
  const examples = config?.sources.examples ?? []
  const known = featured(platforms)

  let sourcesNote: ReactNode
  if (config?.sources.mode === 'allowlist') {
    sourcesNote = (
      <>
        Works with public videos from <span className="text-ink-soft">{listSources(config.sources.domains)}</span>.
      </>
    )
  } else if (known.length > 0) {
    // What a platform really delivers differs from one to the next, so the list says it per platform.
    sourcesNote = (
      <>
        Recognises links from <span className="text-ink-soft">{summarise(known, 4)}</span>.{' '}
        <Link to="/#platforms" className="text-ink-soft underline decoration-line-strong underline-offset-4 hover:text-ink">
          See what works on each
        </Link>
        .
      </>
    )
  } else if (config) {
    sourcesNote = <>Works with public video pages from a wide range of sites.</>
  } else {
    sourcesNote = <>Works with public sources that allow their videos to be downloaded.</>
  }

  return (
    <section id="top" className="relative mx-auto max-w-6xl px-4 pb-10 pt-32 text-center sm:px-6 sm:pt-40">
      <m.div {...fade(0)} className="flex justify-center">
        <ServicePill state={service} onRetry={onRetryService} />
      </m.div>

      <h1 className="mx-auto mt-7 max-w-4xl text-[clamp(2.9rem,9.5vw,6.25rem)] font-semibold leading-[0.98] text-ink">
        <span className="block">
          <Word index={0}>Your</Word> <Word index={1}>Videos.</Word>
        </span>
        <span className="block">
          <span className="inline-block overflow-hidden pb-[0.16em] pr-[0.08em] align-bottom">
            <m.span
              className="text-gradient inline-block animate-gradient-pan bg-[length:200%_auto] font-serif font-normal italic tracking-[-0.01em]"
              initial={{ y: '105%', opacity: 0, filter: 'blur(10px)' }}
              animate={{ y: 0, opacity: 1, filter: 'blur(0px)' }}
              transition={{ duration: 1, delay: 0.34, ease: EASE }}
            >
              Your Way.
            </m.span>
          </span>
        </span>
      </h1>

      <m.p {...fade(0.5)} className="mx-auto mt-6 max-w-xl text-[17px] leading-relaxed text-ink-soft sm:text-lg">
        {namesPlatforms(platforms)
          ? 'Paste a link. Lumora recognises the platform, reads what it really offers and prepares a clean download, with subtitles, in the quality you choose.'
          : 'Paste a link. Lumora reads what the source really offers and prepares a clean download, with subtitles, in the quality you choose.'}
      </m.p>

      <m.div {...fade(0.62)} className="mx-auto mt-9 max-w-3xl">
        <UrlForm
          value={url}
          onChange={onUrlChange}
          onSubmit={onSubmit}
          busy={busy}
          inputRef={inputRef}
          detection={detect(platforms, url)}
        />

        {examples.length > 0 && (
          <div className="mt-2 flex flex-wrap items-center justify-center gap-2 text-[13px]">
            <span className="text-ink-mute">Try an example:</span>
            {examples.map((example) => (
              <button
                key={example.url}
                type="button"
                disabled={busy}
                onClick={() => {
                  onUrlChange(example.url)
                  onSubmit(example.url)
                }}
                className="min-h-9 rounded-full border border-line bg-glass px-3.5 py-1.5 text-ink-soft backdrop-blur-md transition-colors hover:border-line-strong hover:text-ink disabled:opacity-50"
              >
                {example.label} <span className="text-ink-mute">· {example.source}</span>
              </button>
            ))}
          </div>
        )}

        <p className="mx-auto mt-5 max-w-2xl text-[13px] leading-relaxed text-ink-mute">
          {sourcesNote} Videos that are private, paid, region-locked or DRM-protected are never processed, and a
          video that is for adults only asks for your confirmation first.
        </p>
      </m.div>

      {children}

      <m.ul
        {...fade(0.8)}
        className="mx-auto mt-12 flex max-w-3xl flex-wrap items-center justify-center gap-x-8 gap-y-3 text-sm text-ink-soft"
      >
        <li className="inline-flex items-center gap-2">
          <BadgeCheck className="size-4 text-violet" aria-hidden />
          No account needed
        </li>
        <li className="inline-flex items-center gap-2">
          <Captions className="size-4 text-blue" aria-hidden />
          Subtitles as SRT or WebVTT
        </li>
        <li className="inline-flex items-center gap-2">
          <Timer className="size-4 text-cyan" aria-hidden />
          {config ? `Files deleted after ${formatSpan(config.limits.file_ttl_seconds)}` : 'Files deleted automatically'}
        </li>
      </m.ul>
    </section>
  )
}
