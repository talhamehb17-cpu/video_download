import type { ReactNode } from 'react'

import { Reveal } from '../ui/Reveal'

interface SectionHeadingProps {
  eyebrow: string
  title: ReactNode
  children?: ReactNode
  id: string
}

export function SectionHeading({ eyebrow, title, children, id }: SectionHeadingProps) {
  return (
    <Reveal className="mx-auto max-w-2xl text-center">
      <p className="text-[13px] font-medium uppercase tracking-[0.2em] text-cyan">{eyebrow}</p>
      <h2 id={id} className="mt-4 text-[clamp(2rem,5vw,3.25rem)] font-semibold leading-[1.05] text-ink">
        {title}
      </h2>
      {children && <p className="mt-5 text-[17px] leading-relaxed text-ink-soft">{children}</p>}
    </Reveal>
  )
}
