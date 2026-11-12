import { AnimatePresence, m } from 'framer-motion'
import { useEffect, useRef } from 'react'

import type { Downloader } from '../../hooks/useDownloader'
import { Link } from '../../lib/Link'
import { AnalyzingCard } from './AnalyzingCard'
import { ErrorCard } from './ErrorCard'
import { JobPanel } from './JobPanel'
import { ResultCard } from './ResultCard'

interface ProcessingAreaProps {
  downloader: Downloader
  /** How many platforms this service works with (0 when that is not known). */
  platformCount: number
  /** Clear everything and put the cursor back in the link field. */
  onStartOver: () => void
}

const TRANSITION = { duration: 0.45, ease: [0.16, 1, 0.3, 1] as const }

/** Everything that happens after "Analyze" is pressed, one state at a time. */
const PLATFORM_ERRORS = new Set(['domain_not_allowed', 'platform_disabled', 'platform_unsupported'])

export function ProcessingArea({ downloader, platformCount, onStartOver }: ProcessingAreaProps) {
  const { phase } = downloader
  const container = useRef<HTMLDivElement | null>(null)

  const shownKey = useRef('idle')

  let key: string = phase.name
  let content = null

  switch (phase.name) {
    case 'idle':
      break
    case 'analyzing':
      content = <AnalyzingCard url={phase.url} startedAt={phase.startedAt} onCancel={downloader.cancelAnalyze} />
      break
    case 'error':
      content = (
        <ErrorCard
          error={phase.error}
          subject={phase.url}
          // A link this service does not take: point to the ones it does.
          note={
            PLATFORM_ERRORS.has(phase.error.code) && platformCount > 0 ? (
              <>
                Links from {platformCount} platform{platformCount === 1 ? '' : 's'} work.{' '}
                <Link to="/#platforms" className="font-medium text-ink underline decoration-line-strong underline-offset-4 hover:decoration-ink">
                  See the list
                </Link>
                .
              </>
            ) : undefined
          }
          // Only offer "Try again" when asking again could change the answer.
          onRetry={phase.error.retryable ? () => downloader.analyze(phase.url) : undefined}
          onDismiss={onStartOver}
        />
      )
      break
    case 'ready':
      key = `ready-${phase.analysis.id}`
      content = (
        <ResultCard
          analysis={phase.analysis}
          selected={downloader.selectedQuality}
          embedIds={downloader.embedIds}
          starting={phase.starting}
          startError={phase.startError}
          onSelectQuality={downloader.selectQuality}
          onToggleEmbed={downloader.toggleEmbed}
          onStart={downloader.start}
          onReset={onStartOver}
        />
      )
      break
    case 'job':
      key = `job-${phase.job.id}`
      content = (
        <JobPanel
          analysis={phase.analysis}
          job={phase.job}
          fresh={phase.fresh}
          expiresAt={phase.expiresAt}
          busy={phase.busy}
          reconnecting={phase.reconnecting}
          onCancel={downloader.cancel}
          onBack={downloader.backToOptions}
          onReset={onStartOver}
        />
      )
      break
  }

  // Keep the work where the eye is. Each new step glides into place under the
  // navigation bar, unless it already sits there or the visitor has scrolled away
  // to read something else while waiting.
  useEffect(() => {
    const previous = shownKey.current
    shownKey.current = key
    if (key === 'idle' || key === previous) return
    const node = container.current
    if (!node) return
    const rect = node.getBoundingClientRect()
    const requested = previous === 'idle' // the visitor has just pressed "Analyze"
    const watching = rect.bottom > 0 && rect.top < window.innerHeight
    if (!requested && !watching) return
    if (rect.top < 72 || rect.top > window.innerHeight * 0.3) {
      const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
      node.scrollIntoView({ behavior: reduce ? 'auto' : 'smooth', block: 'start' })
    }
  }, [key])

  return (
    <div ref={container} id="download" className="mx-auto mt-8 max-w-4xl scroll-mt-4" aria-live="polite">
      <AnimatePresence mode="wait" initial={false}>
        {content && (
          <m.div
            key={key}
            initial={{ opacity: 0, y: 22, scale: 0.985, filter: 'blur(6px)' }}
            animate={{ opacity: 1, y: 0, scale: 1, filter: 'blur(0px)' }}
            exit={{ opacity: 0, y: -12, scale: 0.99, filter: 'blur(4px)' }}
            transition={TRANSITION}
          >
            {content}
          </m.div>
        )}
      </AnimatePresence>
    </div>
  )
}
