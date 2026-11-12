import { Eye, EyeOff } from 'lucide-react'
import { useId, useState, type InputHTMLAttributes, type ReactNode } from 'react'

import { cn } from '../../lib/cn'

interface FieldProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'onChange' | 'value'> {
  label: string
  value: string
  onChange: (value: string) => void
  hint?: ReactNode
  /** Shows a button that reveals what was typed (for password fields). */
  revealable?: boolean
}

export function Field({ label, value, onChange, hint, revealable = false, type = 'text', className, ...rest }: FieldProps) {
  const id = useId()
  const [shown, setShown] = useState(false)
  return (
    <div className={className}>
      <label htmlFor={id} className="mb-1.5 block text-[13px] font-medium text-ink-soft">
        {label}
      </label>
      <div className="relative">
        <input
          id={id}
          type={revealable && shown ? 'text' : type}
          value={value}
          onChange={(event) => onChange(event.target.value)}
          aria-describedby={hint ? `${id}-hint` : undefined}
          className={cn(
            'h-11 w-full rounded-xl border border-line bg-glass px-3.5 text-[15px] text-ink outline-none transition-colors',
            'placeholder:text-ink-mute hover:border-line-strong focus:border-violet/70 focus:bg-glass-strong',
            revealable && 'pr-11',
          )}
          {...rest}
        />
        {revealable && (
          <button
            type="button"
            onClick={() => setShown((current) => !current)}
            aria-label={shown ? `Hide ${label.toLowerCase()}` : `Show ${label.toLowerCase()}`}
            aria-pressed={shown}
            className="absolute right-1.5 top-1/2 grid size-8 -translate-y-1/2 place-items-center rounded-lg text-ink-mute transition-colors hover:bg-glass-strong hover:text-ink"
          >
            {shown ? <EyeOff className="size-4" aria-hidden /> : <Eye className="size-4" aria-hidden />}
          </button>
        )}
      </div>
      {hint && (
        <p id={`${id}-hint`} className="mt-1.5 text-xs leading-relaxed text-ink-mute">
          {hint}
        </p>
      )}
    </div>
  )
}
