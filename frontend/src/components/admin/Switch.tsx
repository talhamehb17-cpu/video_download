import { cn } from '../../lib/cn'

interface SwitchProps {
  checked: boolean
  onChange: (checked: boolean) => void
  label: string
  disabled?: boolean
  busy?: boolean
}

/** An on/off switch. Colour is never the only signal: the knob moves and the state is announced. */
export function Switch({ checked, onChange, label, disabled = false, busy = false }: SwitchProps) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      aria-busy={busy || undefined}
      disabled={disabled || busy}
      onClick={() => onChange(!checked)}
      className={cn(
        'relative inline-flex h-7 w-12 shrink-0 items-center rounded-full border transition-colors duration-200',
        checked ? 'border-ok/50 bg-ok/25' : 'border-line-strong bg-glass-strong',
        disabled && 'opacity-45',
        busy && 'animate-pulse',
      )}
    >
      <span
        aria-hidden
        className={cn(
          'absolute left-0.5 size-[22px] rounded-full shadow-md transition-transform duration-200',
          checked ? 'translate-x-5 bg-ok' : 'translate-x-0 bg-ink-mute',
        )}
      />
    </button>
  )
}
