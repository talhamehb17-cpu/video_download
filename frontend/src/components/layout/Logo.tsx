import { useId } from 'react'

import { cn } from '../../lib/cn'
import { BRAND } from '../../lib/site'

export function LogoMark({ className }: { className?: string }) {
  const id = useId()
  return (
    <svg viewBox="0 0 64 64" className={cn('size-8', className)} aria-hidden focusable="false">
      <defs>
        <linearGradient id={id} x1="8" y1="6" x2="56" y2="58" gradientUnits="userSpaceOnUse">
          <stop stopColor="#a78bfa" />
          <stop offset=".55" stopColor="#60a5fa" />
          <stop offset="1" stopColor="#22d3ee" />
        </linearGradient>
      </defs>
      <rect width="64" height="64" rx="18" fill={`url(#${id})`} opacity=".16" />
      <rect x=".75" y=".75" width="62.5" height="62.5" rx="17.25" fill="none" stroke={`url(#${id})`} strokeOpacity=".55" strokeWidth="1.5" />
      <path d="M22 14v26a6 6 0 0 0 6 6h16" fill="none" stroke={`url(#${id})`} strokeWidth="7" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M36 18l12 8-12 8z" fill={`url(#${id})`} />
    </svg>
  )
}

export function Logo({ className }: { className?: string }) {
  return (
    <span className={cn('inline-flex items-center gap-2.5', className)}>
      <LogoMark />
      <span className="font-display text-[19px] font-semibold tracking-tight text-ink">{BRAND}</span>
    </span>
  )
}
