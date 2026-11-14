import { m, type HTMLMotionProps } from 'framer-motion'
import { LoaderCircle } from 'lucide-react'
import type { ReactNode } from 'react'

import { buttonClass, type Size, type Variant } from './buttonClass'

interface ButtonProps extends Omit<HTMLMotionProps<'button'>, 'children'> {
  variant?: Variant
  size?: Size
  loading?: boolean
  icon?: ReactNode
  children?: ReactNode
}

export function Button({ variant = 'primary', size = 'md', loading = false, icon, children, className, disabled, type = 'button', ...rest }: ButtonProps) {
  const inactive = disabled || loading
  return (
    <m.button
      type={type}
      disabled={inactive}
      aria-busy={loading || undefined}
      whileHover={inactive ? undefined : { y: -1.5 }}
      whileTap={inactive ? undefined : { scale: 0.97 }}
      transition={{ type: 'spring', stiffness: 500, damping: 30 }}
      className={buttonClass(variant, size, className)}
      {...rest}
    >
      {loading ? <LoaderCircle className="size-4 animate-spin" aria-hidden /> : icon}
      {children}
    </m.button>
  )
}
