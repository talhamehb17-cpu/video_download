import { AnimatePresence, m } from 'framer-motion'
import { useEffect, useRef } from 'react'

import type { Downloader } from '../../hooks/useDownloader'
import { AnalyzingCard } from './AnalyzingCard'
import { ErrorCard } from './ErrorCard'
import { JobPanel } from './JobPanel'
import { ResultCard } from './ResultCard'

interface ProcessingAreaProps {
  downloader: Downloader
  /** Clear everything and put the cursor back in the link field. */
  onStartOver: () => void
}

const TRANSITION = { duration: 0.45, ease: [0.16, 1, 0.3, 1] as const }

/** Everything that happens after "Download" is pressed, one state at a time. */
export function ProcessingArea({ downloader, onStartOver }: ProcessingAreaProps) {
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
    const requested = previous === 'idle' // the visitor has just pressed "Download"
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
