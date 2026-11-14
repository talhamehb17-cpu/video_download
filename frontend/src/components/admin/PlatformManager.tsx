import { CircleAlert, CircleCheck, ListChecks, Plus, Search } from 'lucide-react'
import { useMemo, useState, type FormEvent } from 'react'

import type { Admin } from '../../hooks/useAdmin'
import { adminApi, type AdminPlatform, type AdminPlatforms } from '../../lib/adminApi'
import { FILTERS, filterCounts, filterPlatforms, type PlatformFilter } from '../../lib/adminView'
import { toApiError, type ApiError } from '../../lib/api'
import { cn } from '../../lib/cn'
import { Button } from '../ui/Button'
import { Field } from './Field'
import { PlatformRow } from './PlatformRow'

interface PlatformManagerProps {
  data: AdminPlatforms
  now: number
  call: Admin['call']
  onPlatform: (platform: AdminPlatform) => void
  onRemoved: (id: string) => void
  onReload: () => Promise<void>
}

type Message = { tone: 'ok'; text: string } | { tone: 'bad'; error: ApiError }

function MessageLine({ message }: { message: Message }) {
  const ok = message.tone === 'ok'
  return (
    <p
      role={ok ? 'status' : 'alert'}
      className={cn(
        'flex items-start gap-2 rounded-xl border px-3.5 py-2.5 text-sm',
        ok ? 'border-ok/30 bg-ok/10 text-ink' : 'border-bad/30 bg-bad/10 text-bad',
      )}
    >
      {ok ? <CircleCheck className="mt-0.5 size-4 shrink-0 text-ok" aria-hidden /> : <CircleAlert className="mt-0.5 size-4 shrink-0" aria-hidden />}
      <span>{ok ? message.text : `${message.error.message}${message.error.hint ? ` ${message.error.hint}` : ''}`}</span>
    </p>
  )
}

/** Add a website by its address, or by a link to one of its videos. It is checked at once and stays switched off. */
function AddWebsite({ data, call, onPlatform }: Pick<PlatformManagerProps, 'data' | 'call' | 'onPlatform'>) {
  const [target, setTarget] = useState('')
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<Message | null>(null)

  const submit = async (event: FormEvent) => {
    event.preventDefault()
    const value = target.trim()
    if (!value || busy) return
    setBusy(true)
    setMessage(null)
    try {
      const platform = await call(() => adminApi.add(value, name.trim() || null))
      const known = data.platforms.some((item) => item.id === platform.id)
      onPlatform(platform)
      setTarget('')
      setName('')
      setMessage({
        tone: 'ok',
        text: known
          ? platform.checking
            ? `That address belongs to ${platform.name}, which is already on the list. It is being checked with your link now.`
            : `That address belongs to ${platform.name}, which is already on the list.`
          : `${platform.name} was added and is being checked. It stays switched off until you switch it on.`,
      })
    } catch (caught) {
      const problem = toApiError(caught)
      if (problem.code !== 'not_authenticated') setMessage({ tone: 'bad', error: problem })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form onSubmit={submit} className="glass rounded-2xl p-5" aria-labelledby="add-title">
      <h3 id="add-title" className="font-display text-base font-semibold tracking-tight text-ink">
        Add a website
      </h3>
      <p className="mt-1 text-[13px] leading-relaxed text-ink-soft">
        Enter a domain, or better, a link to a public video on it. Lumora checks at once whether it can read the video and tells you
        how. Nothing is switched on automatically.
      </p>
      <div className="mt-4 grid gap-3 sm:grid-cols-[minmax(0,1fr)_14rem_auto] sm:items-end">
        <Field
          label="Website address or video link"
          name="target"
          inputMode="url"
          autoCapitalize="none"
          spellCheck={false}
          placeholder="example.com or https://example.com/videos/123"
          value={target}
          onChange={setTarget}
        />
        <Field label="Name (optional)" name="name" maxLength={60} placeholder="Shown on the list" value={name} onChange={setName} />
        <Button type="submit" loading={busy} disabled={!target.trim()} icon={<Plus className="size-4" aria-hidden />}>
          Add and check
        </Button>
      </div>
      {message && (
        <div className="mt-4">
          <MessageLine message={message} />
        </div>
      )}
    </form>
  )
}

export function PlatformManager({ data, now, call, onPlatform, onRemoved, onReload }: PlatformManagerProps) {
  const [filter, setFilter] = useState<PlatformFilter>('all')
  const [query, setQuery] = useState('')
  const [bulkBusy, setBulkBusy] = useState(false)
  const [message, setMessage] = useState<Message | null>(null)

  const counts = useMemo(() => filterCounts(data.platforms), [data.platforms])
  const shown = useMemo(() => filterPlatforms(data.platforms, filter, query), [data.platforms, filter, query])
  const checking = data.platforms.filter((platform) => platform.checking).length

  const checkAll = async () => {
    if (bulkBusy) return
    setBulkBusy(true)
    setMessage(null)
    try {
      const { started } = await call(() => adminApi.checkAll())
      await onReload()
      setMessage({
        tone: 'ok',
        text:
          started > 0
            ? `${started} check${started === 1 ? '' : 's'} started. The server runs two at a time, so this takes a few minutes; you can keep working or leave the page.`
            : 'Every platform that is switched on is already being checked.',
      })
    } catch (caught) {
      const problem = toApiError(caught)
      if (problem.code !== 'not_authenticated') setMessage({ tone: 'bad', error: problem })
    } finally {
      setBulkBusy(false)
    }
  }

  return (
    <section aria-labelledby="platforms-title" className="space-y-4">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h2 id="platforms-title" className="font-display text-xl font-semibold tracking-tight text-ink">
            Platforms
          </h2>
          <p className="mt-1 text-sm text-ink-soft">
            {counts.on} of {counts.all} switched on{checking > 0 ? ` · ${checking} being checked` : ''}
          </p>
        </div>
        <Button variant="glass" size="sm" loading={bulkBusy} disabled={counts.on === 0} onClick={() => void checkAll()} icon={<ListChecks className="size-4" aria-hidden />}>
          Check everything that is switched on
        </Button>
      </div>

      {message && <MessageLine message={message} />}

      <AddWebsite data={data} call={call} onPlatform={onPlatform} />

      <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
        <div role="group" aria-label="Filter platforms" className="no-scrollbar -mx-1 flex gap-1.5 overflow-x-auto px-1 py-0.5">
          {FILTERS.map((item) => (
            <button
              key={item.id}
              type="button"
              aria-pressed={filter === item.id}
              onClick={() => setFilter(item.id)}
              className={cn(
                'shrink-0 rounded-full border px-3 py-1.5 text-[13px] transition-colors',
                filter === item.id ? 'border-violet/50 bg-violet/15 text-ink' : 'border-line bg-glass text-ink-soft hover:border-line-strong hover:text-ink',
              )}
            >
              {item.label} <span className="font-mono text-xs tabular-nums text-ink-mute">{counts[item.id]}</span>
            </button>
          ))}
        </div>
        <label className="glass flex h-10 items-center gap-2 rounded-full px-4 lg:w-64">
          <Search className="size-4 shrink-0 text-ink-mute" aria-hidden />
          <span className="sr-only">Search platforms</span>
          <input
            type="search"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder="Search by name or address…"
            className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-mute"
          />
        </label>
      </div>

      {shown.length === 0 ? (
        <p className="glass rounded-2xl p-8 text-center text-sm text-ink-mute">
          {query.trim() ? `Nothing in this group matches “${query.trim()}”.` : 'Nothing in this group.'}
        </p>
      ) : (
        <ul className="space-y-2.5">
          {shown.map((platform) => (
            <PlatformRow key={platform.id} platform={platform} mode={data.mode} now={now} call={call} onPlatform={onPlatform} onRemoved={onRemoved} />
          ))}
        </ul>
      )}
    </section>
  )
}
