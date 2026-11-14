import { AnimatePresence, m } from 'framer-motion'
import { ChevronDown, CircleAlert, Lock, Play, Trash2 } from 'lucide-react'
import { useId, useState, type FormEvent } from 'react'

import type { Admin } from '../../hooks/useAdmin'
import { adminApi, type AdminPlatform, type AdminPlatforms } from '../../lib/adminApi'
import { checkFacts, lockReason } from '../../lib/adminView'
import { toApiError, type ApiError } from '../../lib/api'
import { cn } from '../../lib/cn'
import { formatAgo } from '../../lib/format'
import { Button } from '../ui/Button'
import { StatusBadge } from './StatusBadge'
import { Switch } from './Switch'

interface PlatformRowProps {
  platform: AdminPlatform
  mode: AdminPlatforms['mode']
  now: number
  call: Admin['call']
  onPlatform: (platform: AdminPlatform) => void
  onRemoved: (id: string) => void
}

const EXPECTED: Record<NonNullable<AdminPlatform['expected']>, string> = {
  full: 'Listed as supported',
  partial: 'Listed as partially supported',
  unsupported: 'Listed as unsupported',
}

export function PlatformRow({ platform, mode, now, call, onPlatform, onRemoved }: PlatformRowProps) {
  const panelId = useId()
  const [open, setOpen] = useState(false)
  const [busy, setBusy] = useState<'switch' | 'check' | 'remove' | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [link, setLink] = useState('')
  const [confirming, setConfirming] = useState(false)

  const { check } = platform
  const locked = lockReason(platform)
  const on = platform.enabled && platform.can_enable
  // The switch is on, yet links are declined: another server setting overrules it.
  const overruled = on && !platform.active

  const run = async (kind: 'switch' | 'check' | 'remove', action: () => Promise<AdminPlatform | void>) => {
    if (busy) return
    setBusy(kind)
    setError(null)
    try {
      const updated = await call(action)
      if (updated) onPlatform(updated)
      else onRemoved(platform.id)
    } catch (caught) {
      const problem = toApiError(caught)
      if (problem.code !== 'not_authenticated') {
        setError(problem)
        setOpen(true)
      }
    } finally {
      setBusy(null)
    }
  }

  const checkWithLink = (event: FormEvent) => {
    event.preventDefault()
    const url = link.trim()
    void run('check', () => adminApi.check(platform.id, url || null))
  }

  return (
    <li data-platform={platform.id} className={cn('glass rounded-2xl transition-colors', open && 'border-line-strong')}>
      <div className="grid items-center gap-x-4 gap-y-3 p-4 sm:grid-cols-[minmax(0,1fr)_auto] lg:grid-cols-[minmax(0,15rem)_11.5rem_minmax(0,1fr)_auto]">
        <button
          type="button"
          onClick={() => setOpen((current) => !current)}
          aria-expanded={open}
          aria-controls={panelId}
          className="group flex min-w-0 items-center gap-2.5 rounded-lg text-left"
        >
          <ChevronDown className={cn('size-4 shrink-0 text-ink-mute transition-transform duration-200 group-hover:text-ink', open && 'rotate-180')} aria-hidden />
          <span className="min-w-0">
            <span className="flex items-center gap-2">
              <span className="truncate font-display text-[15px] font-semibold tracking-tight text-ink">{platform.name}</span>
              {!platform.builtin && (
                <span className="shrink-0 rounded-full border border-violet/40 bg-violet/10 px-1.5 py-px text-[10px] font-medium uppercase tracking-wider text-violet">
                  Added
                </span>
              )}
            </span>
            <span className="block truncate font-mono text-[11px] text-ink-mute">{platform.domains.slice(0, 3).join(' · ')}</span>
          </span>
        </button>

        <div className="sm:justify-self-end lg:justify-self-start">
          <StatusBadge status={platform.status} checking={platform.checking} />
        </div>

        <p className="min-w-0 text-[13px] leading-relaxed text-ink-soft sm:col-span-2 lg:col-span-1">
          {platform.checking ? (
            <span className="text-ink-mute">Reading a public video to see what works from this server…</span>
          ) : check ? (
            <>
              <span className="line-clamp-2">{check.summary}</span>
              <span className="text-xs text-ink-mute">Checked {formatAgo(check.at, now / 1000)}</span>
            </>
          ) : (
            <span className="text-ink-mute">
              {platform.expected ? `${EXPECTED[platform.expected]}. Not checked on this server yet.` : 'Not checked yet.'}
            </span>
          )}
        </p>

        <div className="flex items-center justify-between gap-3 sm:col-span-2 lg:col-span-1 lg:justify-end">
          <div className="flex items-center gap-2.5">
            {locked ? (
              <span className="inline-flex items-center gap-1.5 text-xs text-ink-mute" title={locked}>
                <Lock className="size-3.5" aria-hidden />
                Can’t be switched on
              </span>
            ) : (
              <>
                <Switch
                  checked={on}
                  busy={busy === 'switch'}
                  label={`Accept links from ${platform.name}`}
                  onChange={(next) => void run('switch', () => adminApi.setEnabled(platform.id, next))}
                />
                <span className={cn('w-7 text-xs font-medium', on ? 'text-ok' : 'text-ink-mute')} aria-hidden>
                  {on ? 'On' : 'Off'}
                </span>
              </>
            )}
          </div>
          {platform.expected !== 'unsupported' && (
            <Button
              variant="glass"
              size="sm"
              loading={busy === 'check'}
              disabled={platform.checking}
              onClick={() => void run('check', () => adminApi.check(platform.id, null))}
              icon={<Play className="size-3.5" aria-hidden />}
              aria-label={`Check ${platform.name}`}
            >
              Check
            </Button>
          )}
        </div>
      </div>

      <AnimatePresence initial={false}>
        {open && (
          <m.div
            id={panelId}
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
            className="overflow-hidden"
          >
            <div className="space-y-4 border-t border-line p-4 text-[13px] leading-relaxed text-ink-soft">
              {error && (
                <p role="alert" className="flex items-start gap-2 rounded-xl border border-bad/30 bg-bad/10 px-3.5 py-2.5 text-sm text-bad">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <span>
                    {error.message}
                    {error.hint ? ` ${error.hint}` : ''}
                  </span>
                </p>
              )}

              {overruled && (
                <p className="flex items-start gap-2 text-warn">
                  <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />
                  <span className="text-ink-soft">
                    Switched on, but links are still declined:{' '}
                    {mode === 'allowlist' ? 'the server only accepts the domains in ALLOWED_DOMAINS.' : 'a domain of this platform is in BLOCKED_DOMAINS.'}
                  </span>
                </p>
              )}

              <dl className="grid gap-x-8 gap-y-3 sm:grid-cols-2">
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wider text-ink-mute">Addresses</dt>
                  <dd className="mt-1 break-words font-mono text-xs text-ink">{platform.domains.join(', ')}</dd>
                </div>
                <div>
                  <dt className="text-xs font-medium uppercase tracking-wider text-ink-mute">Requests since the API started</dt>
                  <dd className="mt-1 text-ink">
                    {platform.requests_ok} worked · {platform.requests_failed} failed
                  </dd>
                </div>
                {(platform.note || locked) && (
                  <div className="sm:col-span-2">
                    <dt className="text-xs font-medium uppercase tracking-wider text-ink-mute">{locked ? 'Why it can’t be switched on' : 'Known limits'}</dt>
                    <dd className="mt-1 text-ink">{locked ?? platform.note}</dd>
                  </div>
                )}
                {check && (
                  <div className="sm:col-span-2">
                    <dt className="text-xs font-medium uppercase tracking-wider text-ink-mute">Last check</dt>
                    <dd className="mt-1 space-y-1.5">
                      <p className="text-ink">{check.summary}</p>
                      <p className="flex flex-wrap gap-1.5">
                        {checkFacts(check).map((fact) => (
                          <span key={fact} className="rounded-full border border-line bg-glass px-2 py-0.5 text-xs text-ink-soft">
                            {fact}
                          </span>
                        ))}
                      </p>
                      {check.title && <p>Video read: “{check.title}”</p>}
                      {check.url && <p className="break-all font-mono text-xs text-ink-mute">{check.url}</p>}
                      {check.error_code && (
                        <p>
                          {check.error_message} <span className="font-mono text-xs text-ink-mute">({check.error_code})</span>
                        </p>
                      )}
                    </dd>
                  </div>
                )}
              </dl>

              {platform.expected !== 'unsupported' && (
                <form onSubmit={checkWithLink} className="flex flex-col gap-2 sm:flex-row sm:items-end">
                  <label className="min-w-0 flex-1">
                    <span className="mb-1.5 block text-xs font-medium uppercase tracking-wider text-ink-mute">Check with your own link</span>
                    <input
                      type="url"
                      inputMode="url"
                      value={link}
                      onChange={(event) => setLink(event.target.value)}
                      placeholder={`https://${platform.domains[0]?.replace('.*', '.com') ?? 'example.com'}/…`}
                      spellCheck={false}
                      autoCapitalize="none"
                      className="h-10 w-full rounded-xl border border-line bg-glass px-3 font-mono text-[13px] text-ink outline-none transition-colors placeholder:text-ink-mute hover:border-line-strong focus:border-violet/70"
                    />
                  </label>
                  <Button type="submit" variant="glass" size="md" loading={busy === 'check'} disabled={platform.checking || !link.trim()}>
                    Run check
                  </Button>
                </form>
              )}
              <p className="text-xs text-ink-mute">
                A check reads one public video without downloading it and never switches anything on. “Supported” here means it worked
                from this server just now; platforms can change that at any time.
              </p>

              {!platform.builtin && (
                <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
                  {confirming ? (
                    <>
                      <span className="text-sm text-ink">Remove {platform.name} from the list?</span>
                      <Button
                        variant="danger"
                        size="sm"
                        loading={busy === 'remove'}
                        onClick={() => void run('remove', () => adminApi.remove(platform.id))}
                        icon={<Trash2 className="size-3.5" aria-hidden />}
                      >
                        Yes, remove
                      </Button>
                      <Button variant="quiet" size="sm" onClick={() => setConfirming(false)}>
                        Keep it
                      </Button>
                    </>
                  ) : (
                    <Button variant="danger" size="sm" disabled={platform.checking} onClick={() => setConfirming(true)} icon={<Trash2 className="size-3.5" aria-hidden />}>
                      Remove website
                    </Button>
                  )}
                </div>
              )}
            </div>
          </m.div>
        )}
      </AnimatePresence>
    </li>
  )
}
