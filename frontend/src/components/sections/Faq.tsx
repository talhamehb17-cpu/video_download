import { AnimatePresence, m } from 'framer-motion'
import { Plus } from 'lucide-react'
import { useId, useState, type ReactNode } from 'react'

import type { ServiceConfig } from '../../lib/api'
import { cn } from '../../lib/cn'
import { formatBytes, formatSpan } from '../../lib/format'
import { Link } from '../../lib/Link'
import { listSources } from '../../lib/site'
import { Reveal } from '../ui/Reveal'
import { SectionHeading } from './SectionHeading'

interface Entry {
  question: string
  answer: ReactNode
}

function entries(config: ServiceConfig | null): Entry[] {
  const limits = config?.limits
  const sources = config?.sources

  let sourceAnswer: ReactNode
  if (sources?.mode === 'allowlist') {
    sourceAnswer = (
      <>
        <p>
          This service currently accepts links from: <strong className="font-medium text-ink">{listSources(sources.domains)}</strong>.
          These are sources that publish their videos for download and reuse.
        </p>
        <p>Links from other sites are declined with a clear message. The operator of this service decides which sources are enabled.</p>
      </>
    )
  } else if (sources) {
    sourceAnswer = (
      <p>
        Public video pages from a wide range of sites, plus direct links to video files and HLS or DASH streams. A link works only if
        the video is publicly accessible without signing in and the source permits downloading it.
      </p>
    )
  } else {
    sourceAnswer = (
      <p>
        Public video pages from sources that allow their videos to be downloaded. The exact list is set by the operator of this
        service and appears here once the service is connected.
      </p>
    )
  }

  return [
    { question: 'Which sources work?', answer: sourceAnswer },
    {
      question: 'Are subtitles always available?',
      answer: (
        <>
          <p>
            Only when the source publishes them. Lumora lists every subtitle language it finds for a video; if the list is empty,
            the source has none.
          </p>
          <p>
            Tracks created automatically by the source are labelled “Auto-generated”, so you know their accuracy may vary. Lumora
            never invents or machine-translates subtitles.
          </p>
        </>
      ),
    },
    {
      question: 'Which formats can I get?',
      answer: (
        <>
          <p>
            <strong className="font-medium text-ink">Video:</strong> whatever the source provides, usually MP4 or WebM, in each
            resolution it offers. When a source stores video and audio separately, they are merged for you without re-encoding.
            Audio-only files are offered when the source has them.
          </p>
          <p>
            <strong className="font-medium text-ink">Subtitles:</strong> SRT or WebVTT, as separate files, or embedded into MP4,
            WebM and MKV videos.
          </p>
        </>
      ),
    },
    {
      question: 'Why did my link fail?',
      answer: (
        <>
          <p>The message under the field says exactly what happened. The usual reasons are:</p>
          <ul className="list-disc space-y-1.5 pl-5">
            <li>The video is private, needs a sign-in, or is behind a paywall or age check.</li>
            <li>It is region-locked, DRM-protected, or a live stream that hasn’t finished.</li>
            <li>The page has no video, the link is mistyped, or the source isn’t enabled here.</li>
            <li>
              The file is too large{limits ? ` (over ${formatBytes(limits.max_file_size_bytes, { trim: true })})` : ''} or the video too long
              {limits ? ` (over ${formatSpan(limits.max_duration_seconds)})` : ''}.
            </li>
            <li>Too many requests in a short time: wait a moment and try again.</li>
          </ul>
          <p>Lumora never tries to get around these protections.</p>
        </>
      ),
    },
    {
      question: 'What happens to my files, and what do you store?',
      answer: (
        <>
          <p>
            A prepared file stays on the server only so that you can download it. It is deleted automatically{' '}
            {limits ? `after ${formatSpan(limits.file_ttl_seconds)}` : 'after a short time'}, or straight away when you press
            “Delete now” or cancel. Partial downloads are removed immediately.
          </p>
          <p>
            There are no accounts, no advertising and no tracking cookies. Your theme choice is kept in your browser. Server logs
            record the site a link pointed to, never the full link, and only a shortened form of your IP address. See the{' '}
            <Link to="/privacy" className="text-cyan underline decoration-cyan/40 underline-offset-4 hover:decoration-cyan">
              Privacy Policy
            </Link>
            .
          </p>
        </>
      ),
    },
    {
      question: 'Am I allowed to download any video?',
      answer: (
        <p>
          No. Download only what you have the right to: your own videos, public-domain or openly licensed works, or content whose
          owner permits it. You are responsible for how you use what you download. See the{' '}
          <Link to="/terms" className="text-cyan underline decoration-cyan/40 underline-offset-4 hover:decoration-cyan">
            Terms
          </Link>
          .
        </p>
      ),
    },
  ]
}

function Item({ entry, open, onToggle }: { entry: Entry; open: boolean; onToggle: () => void }) {
  const buttonId = useId()
  const panelId = useId()
  return (
    <div className={cn('rounded-2xl border transition-colors duration-300', open ? 'border-line-strong bg-glass-strong' : 'border-line bg-glass hover:border-line-strong')}>
      <h3 className="font-sans tracking-normal">
        <button
          type="button"
          id={buttonId}
          aria-expanded={open}
          aria-controls={panelId}
          onClick={onToggle}
          className="flex w-full items-center justify-between gap-4 rounded-2xl px-5 py-4.5 text-left text-base font-medium text-ink sm:text-[17px]"
        >
          {entry.question}
          <span
            aria-hidden
            className={cn(
              'grid size-8 shrink-0 place-items-center rounded-full border border-line transition-[transform,background-color,color] duration-300',
              open ? 'bg-brand rotate-45 border-transparent text-white' : 'text-ink-soft',
            )}
          >
            <Plus className="size-4" />
          </span>
        </button>
      </h3>
      <AnimatePresence initial={false}>
        {open && (
          <m.div
            id={panelId}
            role="region"
            aria-labelledby={buttonId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.35, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="space-y-3 px-5 pb-5 text-[15px] leading-relaxed text-ink-soft">{entry.answer}</div>
          </m.div>
        )}
      </AnimatePresence>
    </div>
  )
}

export function Faq({ config }: { config: ServiceConfig | null }) {
  const [openIndex, setOpenIndex] = useState<number | null>(0)
  return (
    <section id="faq" aria-labelledby="faq-title" className="mx-auto max-w-3xl px-4 py-16 sm:px-6 sm:py-24">
      <SectionHeading id="faq-title" eyebrow="FAQ" title={<>Questions, <span className="text-gradient font-serif font-normal italic">answered.</span></>} />
      <div className="mt-12 space-y-3">
        {entries(config).map((entry, index) => (
          <Reveal key={entry.question} delay={0.05 * index} offset={16}>
            <Item entry={entry} open={openIndex === index} onToggle={() => setOpenIndex(openIndex === index ? null : index)} />
          </Reveal>
        ))}
      </div>
    </section>
  )
}
