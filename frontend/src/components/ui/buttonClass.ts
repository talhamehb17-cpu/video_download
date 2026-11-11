import { cn } from '../../lib/cn'

export type Variant = 'primary' | 'glass' | 'quiet' | 'danger'
export type Size = 'sm' | 'md' | 'lg'

const BASE =
  'relative inline-flex select-none items-center justify-center gap-2 whitespace-nowrap rounded-full font-medium ' +
  'transition-[background-color,border-color,color,box-shadow,opacity] duration-200 ' +
  'disabled:opacity-55 disabled:saturate-50'

const VARIANTS: Record<Variant, string> = {
  primary:
    'bg-brand text-white shadow-glow hover:shadow-[0_14px_48px_-8px_rgb(124_92_255/0.75),0_2px_12px_-2px_rgb(34_211_238/0.5)] ' +
    'disabled:shadow-none',
  glass: 'border border-line bg-glass text-ink backdrop-blur-md hover:border-line-strong hover:bg-glass-strong',
  quiet: 'text-ink-soft hover:bg-glass hover:text-ink',
  danger: 'border border-bad/35 bg-bad/10 text-bad hover:border-bad/60 hover:bg-bad/15',
}

const SIZES: Record<Size, string> = {
  sm: 'h-9 px-3.5 text-[13px]',
  md: 'h-11 px-5 text-sm',
  lg: 'h-13 px-7 text-[15px]',
}

export function buttonClass(variant: Variant = 'primary', size: Size = 'md', className?: string): string {
  return cn(BASE, VARIANTS[variant], SIZES[size], className)
}
