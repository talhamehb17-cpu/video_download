import { useCallback, useEffect, useRef, useState } from 'react'

import { Hero } from '../components/hero/Hero'
import { ProcessingArea } from '../components/processing/ProcessingArea'
import { Faq } from '../components/sections/Faq'
import { Features } from '../components/sections/Features'
import { HowItWorks } from '../components/sections/HowItWorks'
import { useDownloader } from '../hooks/useDownloader'
import type { ServiceState } from '../hooks/useServiceStatus'
import { usePageEntry } from '../lib/router'
import { NAV_LINKS } from '../lib/site'

interface HomeProps {
  service: ServiceState
  onRetryService: () => void
  onActiveSection: (id: string | null) => void
}

/** Reports which section is under the top third of the viewport (for the nav highlight). */
function useActiveSection(onChange: (id: string | null) => void) {
  useEffect(() => {
    const sections = NAV_LINKS.map((link) => document.getElementById(link.id)).filter((node): node is HTMLElement => node !== null)
    if (sections.length === 0) return
    const visible = new Map<string, number>()
    const observer = new IntersectionObserver(
      (records) => {
        for (const record of records) {
          if (record.isIntersecting) visible.set(record.target.id, record.intersectionRatio)
          else visible.delete(record.target.id)
        }
        // Prefer the last section (in page order) that has entered the band.
        const current = [...NAV_LINKS].reverse().find((link) => visible.has(link.id))
        onChange(current?.id ?? null)
      },
      { rootMargin: '-30% 0px -55% 0px', threshold: [0, 0.01] },
    )
    sections.forEach((section) => observer.observe(section))
    return () => {
      observer.disconnect()
      onChange(null)
    }
  }, [onChange])
}

export default function Home({ service, onRetryService, onActiveSection }: HomeProps) {
  const downloader = useDownloader()
  const [url, setUrl] = useState('')
  const input = useRef<HTMLInputElement | null>(null)
  const config = service.status === 'online' ? service.config : null

  usePageEntry()
  useActiveSection(onActiveSection)

  const { reset } = downloader
  const startOver = useCallback(() => {
    reset()
    setUrl('')
    input.current?.focus({ preventScroll: true })
    document.getElementById('top')?.scrollIntoView({ behavior: 'smooth' })
  }, [reset])

  return (
    <main id="main">
      <Hero
        service={service}
        onRetryService={onRetryService}
        url={url}
        onUrlChange={setUrl}
        onSubmit={downloader.analyze}
        busy={downloader.phase.name === 'analyzing'}
        inputRef={input}
      >
        <ProcessingArea
          downloader={downloader}
          acceptedDomains={config?.sources.mode === 'allowlist' ? config.sources.domains : null}
          onStartOver={startOver}
        />
      </Hero>
      <Features config={config} />
      <HowItWorks />
      <Faq config={config} />
    </main>
  )
}
