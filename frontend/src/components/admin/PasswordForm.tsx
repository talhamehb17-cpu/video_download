import { CircleAlert, KeyRound } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { PASSWORD_MIN, passwordProblem, passwordStrength } from '../../lib/adminView'
import { toApiError } from '../../lib/api'
import { cn } from '../../lib/cn'
import { Button } from '../ui/Button'
import { Field } from './Field'

interface PasswordFormProps {
  email: string
  /** True right after the first sign-in, when the initial password has to be replaced. */
  forced: boolean
  onSubmit: (current: string, next: string) => Promise<void>
  onCancel?: () => void
}

const STRENGTH = ['', 'Too easy to guess', 'Acceptable', 'Good', 'Strong'] as const
const STRENGTH_TONE = ['bg-line-strong', 'bg-bad', 'bg-warn', 'bg-ok', 'bg-ok'] as const

export function PasswordForm({ email, forced, onSubmit, onCancel }: PasswordFormProps) {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const strength = passwordStrength(next)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy) return
    const problem = passwordProblem(current, next, confirm, email)
    if (problem) {
      setError(problem)
      return
    }
    setBusy(true)
    setError(null)
    try {
      await onSubmit(current, next)
    } catch (caught) {
      const failure = toApiError(caught)
      setError(failure.code === 'not_authenticated' ? null : failure.message)
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} noValidate aria-labelledby="password-title">
      <div className="flex items-start gap-4">
        <div className="bg-brand grid size-11 shrink-0 place-items-center rounded-2xl text-white shadow-glow">
          <KeyRound className="size-5" aria-hidden />
        </div>
        <div>
          <h2 id="password-title" className="text-xl font-semibold text-ink">
            {forced ? 'Choose your own password' : 'Change password'}
          </h2>
          <p className="mt-1 text-sm leading-relaxed text-ink-soft">
            {forced
              ? 'You signed in with the initial password from the server’s configuration. It has to be replaced before anything else can be done; after that it no longer works.'
              : 'Changing the password signs out every other device.'}
          </p>
        </div>
      </div>

      {error && (
        <p role="alert" className="mt-5 flex items-start gap-2 rounded-xl border border-bad/30 bg-bad/10 px-3.5 py-2.5 text-sm text-bad">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          {error}
        </p>
      )}

      {/* Lets password managers file the new password under the right account. */}
      <input type="email" name="username" autoComplete="username" value={email} readOnly hidden />

      <div className="mt-6 space-y-4">
        <Field
          label={forced ? 'Initial password' : 'Current password'}
          type="password"
          name="current-password"
          autoComplete="current-password"
          required
          revealable
          value={current}
          onChange={setCurrent}
        />
        <div>
          <Field
            label="New password"
            type="password"
            name="new-password"
            autoComplete="new-password"
            required
            revealable
            minLength={PASSWORD_MIN}
            value={next}
            onChange={setNext}
            hint={`At least ${PASSWORD_MIN} characters. A few unrelated words make a strong password that is easy to type.`}
          />
          <div className="mt-2 flex items-center gap-3" aria-live="polite">
            <div className="flex flex-1 gap-1" aria-hidden>
              {[1, 2, 3, 4].map((step) => (
                <span key={step} className={cn('h-1 flex-1 rounded-full transition-colors', strength >= step ? STRENGTH_TONE[strength] : 'bg-line-strong')} />
              ))}
            </div>
            <span className="min-w-28 text-right text-xs text-ink-mute">{STRENGTH[strength]}</span>
          </div>
        </div>
        <Field
          label="New password, again"
          type="password"
          name="confirm-password"
          autoComplete="new-password"
          required
          revealable
          value={confirm}
          onChange={setConfirm}
        />
      </div>

      <div className="mt-7 flex flex-wrap items-center gap-3">
        <Button type="submit" loading={busy} disabled={!current || !next || !confirm}>
          {forced ? 'Save and continue' : 'Change password'}
        </Button>
        {onCancel && (
          <Button variant="quiet" onClick={onCancel} disabled={busy}>
            Cancel
          </Button>
        )}
      </div>
    </form>
  )
}
