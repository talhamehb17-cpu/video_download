import { m } from 'framer-motion'
import { CircleAlert, Info, LockKeyhole } from 'lucide-react'
import { useState, type FormEvent } from 'react'

import { useCountdown } from '../../hooks/useCountdown'
import { toApiError, type ApiError } from '../../lib/api'
import { formatClock } from '../../lib/format'
import { Button } from '../ui/Button'
import { Field } from './Field'

interface SignInProps {
  notice: string | null
  onSignIn: (email: string, password: string) => Promise<void>
}

export function SignIn({ notice, onSignIn }: SignInProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<ApiError | null>(null)
  // After repeated failures the server pauses sign-in; the form waits with it.
  const [pausedUntil, setPausedUntil] = useState<number | null>(null)
  const wait = useCountdown(pausedUntil)
  const paused = wait !== null && wait > 0

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    if (busy || paused) return
    setBusy(true)
    setError(null)
    try {
      await onSignIn(email.trim(), password)
    } catch (caught) {
      const problem = toApiError(caught)
      setError(problem)
      setPassword('')
      setPausedUntil(problem.status === 429 && problem.retryAfter ? Date.now() + problem.retryAfter * 1000 : null)
    } finally {
      setBusy(false)
    }
  }

  return (
    <m.form
      onSubmit={submit}
      initial={{ opacity: 0, y: 16 }}
      animate={{ opacity: 1, y: 0 }}
      transition={{ duration: 0.45, ease: [0.16, 1, 0.3, 1] }}
      className="glass glow-border mx-auto w-full max-w-md rounded-3xl p-6 sm:p-8"
      aria-labelledby="sign-in-title"
      noValidate
    >
      <div className="bg-brand grid size-12 place-items-center rounded-2xl text-white shadow-glow">
        <LockKeyhole className="size-5" aria-hidden />
      </div>
      <h1 id="sign-in-title" className="mt-5 text-2xl font-semibold text-ink">
        Administrator sign-in
      </h1>
      <p className="mt-1.5 text-sm leading-relaxed text-ink-soft">Manage platforms and see how the service is doing.</p>

      {notice && !error && (
        <p role="status" className="mt-5 flex items-start gap-2 rounded-xl border border-line bg-glass px-3.5 py-2.5 text-sm text-ink-soft">
          <Info className="mt-0.5 size-4 shrink-0 text-blue" aria-hidden />
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-5 flex items-start gap-2 rounded-xl border border-bad/30 bg-bad/10 px-3.5 py-2.5 text-sm text-bad">
          <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
          <span>
            {error.message}
            {paused ? ` Try again in ${formatClock(wait)}.` : error.hint && !error.retryAfter ? ` ${error.hint}` : ''}
          </span>
        </p>
      )}

      <div className="mt-6 space-y-4">
        <Field
          label="E-mail address"
          type="email"
          name="email"
          autoComplete="username"
          inputMode="email"
          autoCapitalize="none"
          spellCheck={false}
          required
          value={email}
          onChange={setEmail}
        />
        <Field
          label="Password"
          type="password"
          name="password"
          autoComplete="current-password"
          required
          revealable
          value={password}
          onChange={setPassword}
        />
      </div>

      <Button type="submit" size="lg" className="mt-7 w-full" loading={busy} disabled={paused || !email.trim() || !password}>
        {paused ? `Wait ${formatClock(wait)}` : 'Sign in'}
      </Button>
    </m.form>
  )
}
