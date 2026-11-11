import { Captions, MonitorPlay, MousePointerClick, ShieldCheck, Zap, type LucideIcon } from 'lucide-react'

import type { ServiceConfig } from '../../lib/api'
import { cn } from '../../lib/cn'
import { formatBytes, formatSpan } from '../../lib/format'
import { Reveal } from '../ui/Reveal'
import { onSpotlightMove } from '../ui/useSpotlight'
import { SectionHeading } from './SectionHeading'

interface Feature {
  icon: LucideIcon
  title: string
  text: string
  points: string[]
  tint: string
  wide?: boolean
}

function features(config: ServiceConfig | null): Feature[] {
  const ttl = config ? formatSpan(config.limits.file_ttl_seconds) : null
  const maxSize = config ? formatBytes(config.limits.max_file_size_bytes, { trim: true }) : null
  return [
    {
      icon: MonitorPlay,
      title: 'High-quality downloads',
      text: 'You see every quality the source actually provides, with its real format, codec and size. Nothing is upscaled or re-encoded.',
      points: ['Up to the source’s best resolution', 'Separate video and audio merged for you', maxSize ? `Files up to ${maxSize}` : 'Audio-only when the source offers it'],
      tint: 'from-violet/30',
      wide: true,
    },
    {
      icon: Captions,
      title: 'Subtitle support',
      text: 'Every subtitle language the source publishes is listed. Download any track as SRT or WebVTT, or embed it into the video.',
      points: ['SRT and WebVTT', 'Optional embedding'],
      tint: 'from-blue/30',
    },
    {
      icon: Zap,
      title: 'Fast processing',
      text: 'Links are analyzed in seconds and files are prepared in the background, with live progress, speed and time remaining.',
      points: ['Real progress, not a spinner', 'Cancel at any moment'],
      tint: 'from-cyan/30',
    },
    {
      icon: MousePointerClick,
      title: 'Clean interface',
      text: 'One field, one button. No ads, no pop-ups, no account. Clear messages when something can’t be downloaded, and why.',
      points: ['Works on phone, tablet and desktop', 'Keyboard and screen-reader friendly'],
      tint: 'from-violet/30',
    },
    {
      icon: ShieldCheck,
      title: 'Private by design',
      text: `Prepared files are temporary: they are deleted ${ttl ? `after ${ttl}` : 'automatically'}, or immediately when you ask. There are no trackers and nothing to sign up for.`,
      points: ['Automatic deletion', 'No tracking cookies'],
      tint: 'from-cyan/30',
      wide: true,
    },
  ]
}

export function Features({ config }: { config: ServiceConfig | null }) {
  return (
    <section id="features" aria-labelledby="features-title" className="mx-auto max-w-6xl px-4 py-16 sm:px-6 sm:py-24">
      <SectionHeading id="features-title" eyebrow="Features" title={<>Everything you need. <span className="text-gradient block font-serif font-normal italic">Nothing you don’t.</span></>}>
        A focused tool that tells you the truth about what a source offers, then gets out of your way.
      </SectionHeading>

      <ul className="mt-12 grid gap-4 md:grid-cols-6">
        {features(config).map((feature, index) => (
          <Reveal key={feature.title} delay={0.06 * index} className={cn('md:col-span-3', feature.wide ? 'lg:col-span-4' : 'lg:col-span-2')}>
            <li
              onPointerMove={onSpotlightMove}
              className="spotlight glass group relative h-full list-none overflow-hidden rounded-3xl p-6 transition-[transform,border-color] duration-300 hover:-translate-y-1 hover:border-line-strong sm:p-7"
            >
              <div aria-hidden className={cn('absolute -right-16 -top-16 size-48 rounded-full bg-radial to-transparent opacity-60 blur-2xl transition-opacity duration-500 group-hover:opacity-100', feature.tint)} />
              <div className="relative">
                <div className="glow-border grid size-12 place-items-center rounded-2xl bg-glass-strong text-ink transition-transform duration-300 group-hover:scale-110 group-hover:-rotate-3">
                  <feature.icon className="size-5" aria-hidden />
                </div>
                <h3 className="mt-5 text-xl font-semibold text-ink">{feature.title}</h3>
                <p className="mt-2.5 max-w-xl text-[15px] leading-relaxed text-ink-soft">{feature.text}</p>
                <ul className="mt-5 flex flex-wrap gap-2">
                  {feature.points.map((point) => (
                    <li key={point} className="rounded-full border border-line bg-glass px-3 py-1 text-xs text-ink-soft">
                      {point}
                    </li>
                  ))}
                </ul>
              </div>
            </li>
          </Reveal>
        ))}
      </ul>
    </section>
  )
}
