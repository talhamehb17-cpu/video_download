import { useCallback, useEffect, useRef, useState } from 'react'

import { Hero } from '../components/hero/Hero'
import { ProcessingArea } from '../components/processing/ProcessingArea'
import { Faq } from '../components/sections/Faq'
import { Features } from '../components/sections/Features'
import { HowItWorks } from '../components/sections/HowItWorks'
import { Platforms } from '../components/sections/Platforms'
import { useDownloader } from '../hooks/useDownloader'
import type { ServiceState } from '../hooks/useServiceStatus'
import { ApiError } from '../lib/api'
import { refusalFor, usable, type PlatformList } from '../lib/platforms'
import { usePageEntry } from '../lib/router'
import { NAV_LINKS } from '../lib/site'

interface HomeProps {
  service: ServiceState
  onRetryService: () => void
  refreshPlatforms: () => Promise<PlatformList | null>
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

export default function Home({ service, onRetryService, refreshPlatforms, onActiveSection }: HomeProps) {
  const downloader = useDownloader()
  const [url, setUrl] = useState('')
  const input = useRef<HTMLInputElement | null>(null)
  const config = service.status === 'online' ? service.config : null
  const platforms = service.status === 'online' ? service.platforms : null

  // A link the service's own list rules out is answered here, at once, instead of
  // being sent only to be declined. The list is fetched again first, so a platform
  // that was switched on a minute ago is not turned away by an old copy; if the
  // list cannot be fetched, the link is sent and the service decides.
  const { analyze, refuse } = downloader
  const submit = useCallback(
    (link: string) => {
      if (!refusalFor(platforms, link)) {
        analyze(link)
        return
      }
      void refreshPlatforms().then((latest) => {
        const refusal = refusalFor(latest, link)
        if (refusal) refuse(link, new ApiError(refusal.code, refusal.message, { hint: refusal.hint, status: 422 }))
        else analyze(link)
      })
    },
    [platforms, analyze, refuse, refreshPlatforms],
  )

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
        onSubmit={submit}
        busy={downloader.phase.name === 'analyzing'}
        inputRef={input}
      >
        <ProcessingArea downloader={downloader} platformCount={usable(platforms).length} onStartOver={startOver} />
      </Hero>
      <Features config={config} />
      <Platforms list={platforms} />
      <HowItWorks />
      <Faq config={config} />
    </main>
  )
}
