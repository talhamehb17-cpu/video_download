import { m, type HTMLMotionProps } from 'framer-motion'

interface RevealProps extends HTMLMotionProps<'div'> {
  delay?: number
  /** Distance travelled while fading in, in pixels. */
  offset?: number
}

/** Fades content up the first time it scrolls into view. */
export function Reveal({ delay = 0, offset = 26, children, ...rest }: RevealProps) {
  return (
    <m.div
      initial={{ opacity: 0, y: offset }}
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: '0px 0px -12% 0px' }}
      transition={{ duration: 0.75, delay, ease: [0.16, 1, 0.3, 1] }}
      {...rest}
    >
      {children}
    </m.div>
  )
}
