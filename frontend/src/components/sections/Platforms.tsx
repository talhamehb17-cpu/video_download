import { m } from 'framer-motion'
import { BadgeCheck, CircleAlert, CircleSlash, Search, type LucideIcon } from 'lucide-react'
import { useMemo, useState } from 'react'

import { cn } from '../../lib/cn'
import { STATUS_LABEL, featured, type Platform, type PlatformList, type PlatformStatus } from '../../lib/platforms'
import { Reveal } from '../ui/Reveal'
import { SectionHeading } from './SectionHeading'

type Group = 'working' | 'unsupported'

/** Cards shown before "Show all": three rows on a desktop, and half of that on a phone. */
const COLLAPSED = 9
const COLLAPSED_PHONE = 5

const TONE: Record<PlatformStatus, { badge: string; Icon: LucideIcon }> = {
  supported: { badge: 'border-ok/30 bg-ok/10 text-ok', Icon: BadgeCheck },
  partial: { badge: 'border-warn/30 bg-warn/10 text-warn', Icon: CircleAlert },
  unsupported: { badge: 'border-bad/30 bg-bad/10 text-bad', Icon: CircleSlash },
}

function isWorking(platform: Platform): boolean {
  return platform.enabled && platform.status !== 'unsupported'
}

/** What the last compatibility check on the server saw. Only a check that tested a link counts. */
function lastCheck(platform: Platform): { text: string; tone: string; worked: boolean } {
  if (!platform.checked_at) return { text: 'Not checked on this server yet', tone: 'text-ink-mute', worked: false }
  const day = new Date(platform.checked_at * 1000).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: 'numeric' })
  return platform.verified
    ? { text: `Worked from this server on ${day}`, tone: 'text-ok', worked: true }
    : { text: `Didn’t work from this server on ${day}`, tone: 'text-warn', worked: false }
}

function PlatformCard({ platform }: { platform: Platform }) {
  const working = isWorking(platform)
  // A platform that is switched off is, for a visitor, simply not usable.
  const status: PlatformStatus = working ? platform.status : 'unsupported'
  const { badge, Icon } = TONE[status]
  const off = !platform.enabled && platform.status !== 'unsupported'
  const check = lastCheck(platform)
  return (
    <div className="glass flex h-full flex-col rounded-2xl p-4 text-left transition-[transform,border-color] duration-300 hover:-translate-y-0.5 hover:border-line-strong">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate font-display text-[15px] font-semibold tracking-tight text-ink">{platform.name}</h3>
          <p className="mt-0.5 truncate font-mono text-[11px] text-ink-mute">{platform.domains.slice(0, 2).join(' · ')}</p>
        </div>
        <span className={cn('inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-[11px] font-medium', badge)}>
          <Icon className="size-3" aria-hidden />
          {off ? 'Switched off' : STATUS_LABEL[status]}
        </span>
      </div>
      {(platform.note || off) && (
        <p className="mt-2.5 text-[13px] leading-relaxed text-ink-soft">
          {off ? 'The operator of this service has switched this platform off.' : platform.note}
        </p>
      )}
      {working && platform.verified !== undefined && (
        <p className={cn('mt-auto flex items-center gap-1.5 pt-3 text-[11px]', check.tone)} data-check={check.worked ? 'worked' : platform.checked_at ? 'failed' : 'none'}>
          {check.worked && <BadgeCheck className="size-3" aria-hidden />}
          {!check.worked && platform.checked_at != null && <CircleAlert className="size-3" aria-hidden />}
          {check.text}
        </p>
      )}
    </div>
  )
}

/** Every platform the service knows, with what to expect from each. Straight from the API. */
export function Platforms({ list }: { list: PlatformList | null }) {
  const [group, setGroup] = useState<Group>('working')
  const [query, setQuery] = useState('')
  const [expanded, setExpanded] = useState(false)

  const working = useMemo(() => featured(list), [list])
  const unsupported = useMemo(() => (list?.platforms ?? []).filter((platform) => !isWorking(platform)), [list])
  const total = working.length + unsupported.length

  const needle = query.trim().toLowerCase()
  const shown = useMemo(() => {
    const pool = group === 'working' ? working : unsupported
    if (!needle) return pool
    return pool.filter((platform) => platform.name.toLowerCase().includes(needle) || platform.domains.some((domain) => domain.includes(needle)))
  }, [group, working, unsupported, needle])

  const open = expanded || needle !== ''
  const collapsible = !needle && shown.length > COLLAPSED_PHONE
  const groups: Array<{ id: Group; label: string; count: number }> = [
    { id: 'working', label: 'Works', count: working.length },
    { id: 'unsupported', label: 'Not supported', count: unsupported.length },
  ]

  return (
    <section aria-labelledby="platforms-title" className="mx-auto max-w-6xl px-4 py-24 sm:px-6 sm:py-28">
      <div id="platforms" className="scroll-mt-24" />
      <SectionHeading eyebrow="Platforms" id="platforms-title" title="Paste a link. Lumora knows where it’s from.">
        The platform is recognised from the link itself, including short links and country versions. Each one is listed with
        what you can honestly expect from it.
      </SectionHeading>

      {list === null ? (
        <Reveal className="mx-auto mt-12 max-w-xl text-center text-sm text-ink-mute">
          The list appears here as soon as the download service is connected.
        </Reveal>
      ) : (
        <Reveal className="mt-12">
          <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
            {/* With nothing in the second group there is nothing to choose between. */}
            <div
              role="group"
              aria-label="Which platforms to show"
              className={cn('glass inline-flex self-start rounded-full p-1', unsupported.length === 0 && 'hidden')}
            >
              {groups.map((item) => (
                <button
                  key={item.id}
                  type="button"
                  aria-pressed={group === item.id}
                  onClick={() => {
                    setGroup(item.id)
                    setExpanded(false)
                  }}
                  className={cn(
                    'rounded-full px-4 py-1.5 text-sm transition-colors duration-200',
                    group === item.id ? 'bg-glass-strong text-ink' : 'text-ink-mute hover:text-ink-soft',
                  )}
                >
                  {item.label} <span className="font-mono text-xs tabular-nums text-ink-mute">{item.count}</span>
                </button>
              ))}
            </div>
            {total > COLLAPSED && (
              <label className="glass flex h-10 items-center gap-2 rounded-full px-4 sm:w-64">
                <Search className="size-4 shrink-0 text-ink-mute" aria-hidden />
                <span className="sr-only">Search platforms</span>
                <input
                  type="search"
                  value={query}
                  onChange={(event) => setQuery(event.target.value)}
                  placeholder="Search a platform…"
                  className="min-w-0 flex-1 bg-transparent text-sm text-ink outline-none placeholder:text-ink-mute"
                />
              </label>
            )}
          </div>

          {shown.length === 0 ? (
            <p className="mt-10 text-center text-sm text-ink-mute">
              {needle ? `Nothing in this group matches “${query.trim()}”.` : 'Nothing in this group.'}
            </p>
          ) : (
            <ul className="mt-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {shown.map((platform, index) => (
                <m.li
                  key={`${group}-${platform.id}`}
                  data-platform={platform.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  transition={{ duration: 0.25, delay: Math.min(index, 8) * 0.02 }}
                  className={cn(!open && index >= COLLAPSED && 'hidden', !open && index >= COLLAPSED_PHONE && index < COLLAPSED && 'max-sm:hidden')}
                >
                  <PlatformCard platform={platform} />
                </m.li>
              ))}
            </ul>
          )}

          {collapsible && (
            <div className={cn('mt-6 text-center', shown.length <= COLLAPSED && 'sm:hidden')}>
              <button
                type="button"
                onClick={() => setExpanded((value) => !value)}
                aria-expanded={expanded}
                className="rounded-full border border-line bg-glass px-5 py-2 text-sm text-ink-soft backdrop-blur-md transition-colors hover:border-line-strong hover:text-ink"
              >
                {expanded ? 'Show fewer' : `Show all ${shown.length} platforms`}
              </button>
            </div>
          )}

          <p className="mx-auto mt-8 max-w-2xl text-center text-[13px] leading-relaxed text-ink-mute">
            “Partially supported” means public videos work within the limits named on the card. Large platforms can turn a
            server away at any time; when that happens Lumora says so, and it never signs in or works around a block.
          </p>
        </Reveal>
      )}
    </section>
  )
}
