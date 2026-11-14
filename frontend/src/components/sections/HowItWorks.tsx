import { m } from 'framer-motion'
import { ArrowDownToLine, ClipboardPaste, ScanSearch, SlidersHorizontal, type LucideIcon } from 'lucide-react'

import { Reveal } from '../ui/Reveal'
import { SectionHeading } from './SectionHeading'

const READS = 'the link and reads the title, preview, duration, qualities and subtitles.'

function steps(recognises: boolean): Array<{ icon: LucideIcon; title: string; text: string }> {
  return [
    { icon: ClipboardPaste, title: 'Paste URL', text: 'Copy the address of a public video page and paste it into the field.' },
    { icon: ScanSearch, title: 'Analyze', text: recognises ? `Lumora recognises the platform, checks ${READS}` : `Lumora checks ${READS}` },
    { icon: SlidersHorizontal, title: 'Choose quality & subtitles', text: 'Pick a resolution and format, and decide which subtitle tracks you want.' },
    { icon: ArrowDownToLine, title: 'Download', text: 'Watch the file being prepared, then save it. It is deleted from the server afterwards.' },
  ]
}

/** `recognises`: the service names its platforms, so a link can be recognised before it is sent. */
export function HowItWorks({ recognises = true }: { recognises?: boolean }) {
  const STEPS = steps(recognises)
  return (
    <section id="how-it-works" aria-labelledby="how-title" className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
      <SectionHeading id="how-title" eyebrow="How it works" title={<>From link to file in <span className="text-gradient font-serif font-normal italic">four steps.</span></>}>
        No extensions, no installs. It all happens in this page.
      </SectionHeading>

      <ol className="relative mt-14 grid gap-6 sm:grid-cols-2 sm:gap-10 lg:grid-cols-4 lg:gap-6">
        {/* connecting line that draws itself as the row scrolls into view */}
        <m.span
          aria-hidden
          className="absolute left-[12.5%] right-[12.5%] top-8 hidden h-px origin-left bg-linear-to-r from-violet via-blue to-cyan lg:block"
          initial={{ scaleX: 0, opacity: 0 }}
          whileInView={{ scaleX: 1, opacity: 0.55 }}
          viewport={{ once: true, margin: '0px 0px -20% 0px' }}
          transition={{ duration: 1.4, ease: [0.16, 1, 0.3, 1], delay: 0.2 }}
        />
        {STEPS.map((step, index) => (
          <Reveal key={step.title} delay={0.12 * index}>
            <li className="group relative flex list-none flex-col items-center text-center">
              <div className="glow-border relative grid size-16 place-items-center rounded-2xl bg-bg-soft shadow-panel transition-transform duration-300 group-hover:-translate-y-1">
                <step.icon className="size-6 text-ink" aria-hidden />
                <span className="bg-brand absolute -right-2.5 -top-2.5 grid size-6 place-items-center rounded-full font-mono text-[11px] font-semibold text-white shadow-glow">
                  {index + 1}
                </span>
              </div>
              <h3 className="mt-6 text-lg font-semibold text-ink">{step.title}</h3>
              <p className="mt-2 max-w-[17rem] text-[15px] leading-relaxed text-ink-soft">{step.text}</p>
              {index < STEPS.length - 1 && (
                <span aria-hidden className="mt-6 h-9 w-px bg-linear-to-b from-blue/70 to-transparent sm:hidden" />
              )}
            </li>
          </Reveal>
        ))}
      </ol>
    </section>
  )
}
