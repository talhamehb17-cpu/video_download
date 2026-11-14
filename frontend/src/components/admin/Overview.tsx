import { Activity, CircleAlert, HardDrive, Layers, Server, TriangleAlert, type LucideIcon } from 'lucide-react'
import type { ReactNode } from 'react'

import type { AdminOverview } from '../../lib/adminApi'
import { cn } from '../../lib/cn'
import { formatAgo, formatBytes, formatSpan, formatUptime } from '../../lib/format'

function Tile({ icon: Icon, title, value, children }: { icon: LucideIcon; title: string; value: ReactNode; children: ReactNode }) {
  return (
    <div className="glass flex flex-col rounded-2xl p-5">
      <p className="flex items-center gap-2 text-[13px] font-medium text-ink-mute">
        <Icon className="size-4 text-cyan" aria-hidden />
        {title}
      </p>
      <p className="mt-3 font-display text-[28px] font-semibold leading-none tracking-tight text-ink">{value}</p>
      <div className="mt-3 space-y-1 text-[13px] leading-relaxed text-ink-soft">{children}</div>
    </div>
  )
}

function Warning({ tone, children }: { tone: 'warn' | 'bad' | 'info'; children: ReactNode }) {
  const Icon = tone === 'info' ? CircleAlert : TriangleAlert
  return (
    <p
      role={tone === 'bad' ? 'alert' : 'status'}
      className={cn(
        'flex items-start gap-2.5 rounded-2xl border px-4 py-3 text-sm leading-relaxed',
        tone === 'bad' && 'border-bad/30 bg-bad/10 text-ink',
        tone === 'warn' && 'border-warn/30 bg-warn/10 text-ink',
        tone === 'info' && 'border-line bg-glass text-ink-soft',
      )}
    >
      <Icon className={cn('mt-0.5 size-4 shrink-0', tone === 'bad' ? 'text-bad' : tone === 'warn' ? 'text-warn' : 'text-blue')} aria-hidden />
      <span>{children}</span>
    </p>
  )
}

const MODE_TEXT: Record<AdminOverview['mode'], string> = {
  platforms: 'Platforms that are switched on',
  open: 'Any website, except platforms switched off',
  allowlist: 'Only the domains in ALLOWED_DOMAINS',
}

const STAGE: Record<string, string> = { analyze: 'Reading a link', download: 'Downloading' }

export function Overview({ overview, now }: { overview: AdminOverview; now: number }) {
  const { disk, counts } = overview
  const used = Math.max(0, disk.total_bytes - disk.free_bytes)
  const usedShare = disk.total_bytes > 0 ? Math.min(100, (used / disk.total_bytes) * 100) : 0
  // What a new download may still use: free space, minus what running jobs were promised, minus the margin.
  const available = Math.max(0, disk.free_bytes - disk.reserved_bytes - disk.floor_bytes)
  const tight = available < overview.max_file_size_bytes
  const full = disk.free_bytes <= disk.floor_bytes

  return (
    <section aria-labelledby="overview-title">
      <h2 id="overview-title" className="sr-only">
        Overview
      </h2>

      <div className="space-y-3">
        {!overview.persistent && (
          <Warning tone="bad">
            Changes can’t be saved to disk, so they are lost when the API restarts. Make the folder named in{' '}
            <code className="font-mono text-[13px]">DATA_DIR</code> writable for the service’s user.
          </Warning>
        )}
        {overview.mode === 'allowlist' && (
          <Warning tone="warn">
            The server runs with <code className="font-mono text-[13px]">SOURCE_POLICY=allowlist</code>: only the domains in{' '}
            <code className="font-mono text-[13px]">ALLOWED_DOMAINS</code> are accepted and the switches below have no effect. Set{' '}
            <code className="font-mono text-[13px]">SOURCE_POLICY=platforms</code> and restart the API to manage platforms here.
          </Warning>
        )}
        {overview.mode === 'open' && (
          <Warning tone="info">
            The server runs with <code className="font-mono text-[13px]">SOURCE_POLICY=open</code>: links from any website are
            accepted, except platforms that are switched off here.
          </Warning>
        )}
        {full ? (
          <Warning tone="bad">
            The disk is full up to the safety margin ({formatBytes(disk.floor_bytes, { trim: true })}). New downloads are refused
            until files expire or space is freed.
          </Warning>
        ) : (
          tight && (
            <Warning tone="warn">
              There is room for {formatBytes(available, { trim: true })} of new downloads, less than the largest file allowed (
              {formatBytes(overview.max_file_size_bytes, { trim: true })}). Large downloads will be refused.
            </Warning>
          )
        )}
      </div>

      <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Tile icon={Layers} title="Platforms switched on" value={counts.enabled ?? 0}>
          <p>
            {counts.supported ?? 0} supported · {counts.partial ?? 0} partial
          </p>
          <p>
            {counts.requires_review ?? 0} require review · {counts.unsupported ?? 0} unsupported
          </p>
        </Tile>

        <Tile icon={HardDrive} title="Free disk space" value={formatBytes(disk.free_bytes, { trim: true })}>
          <div
            role="meter"
            aria-label="Disk space in use"
            aria-valuemin={0}
            aria-valuemax={100}
            aria-valuenow={Math.round(usedShare)}
            className="h-1.5 overflow-hidden rounded-full bg-glass-strong"
          >
            <div className={cn('h-full rounded-full', full ? 'bg-bad' : tight ? 'bg-warn' : 'bg-ok')} style={{ width: `${usedShare}%` }} />
          </div>
          <p className="pt-1">
            of {formatBytes(disk.total_bytes, { trim: true })} · files kept: {formatBytes(disk.used_bytes, { trim: true })}
          </p>
          <p>
            Reserved: {formatBytes(disk.reserved_bytes, { trim: true })} · margin: {formatBytes(disk.floor_bytes, { trim: true })}
            {disk.budget_bytes ? ` · budget: ${formatBytes(disk.budget_bytes, { trim: true })}` : ''}
          </p>
        </Tile>

        <Tile icon={Activity} title="Downloads running" value={`${overview.running_jobs} / ${overview.max_concurrent_jobs}`}>
          <p>
            {overview.queued_jobs} waiting · {overview.kept_files} finished file{overview.kept_files === 1 ? '' : 's'} kept
          </p>
          <p>
            Files up to {formatBytes(overview.max_file_size_bytes, { trim: true })}, deleted after {formatSpan(overview.file_ttl_seconds)}
          </p>
        </Tile>

        <Tile icon={Server} title="API version" value={overview.version}>
          <p>
            yt-dlp {overview.extractor_version} · ffmpeg {overview.ffmpeg ? 'found' : 'missing'}
          </p>
          <p>
            Running for {formatUptime(overview.uptime_seconds)} · {overview.environment}
          </p>
          <p className="text-ink-mute">Accepts: {MODE_TEXT[overview.mode].toLowerCase()}</p>
        </Tile>
      </div>

      <div className="glass mt-4 rounded-2xl p-5">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h3 className="font-display text-base font-semibold tracking-tight text-ink">Recent errors</h3>
          <p className="text-xs text-ink-mute">Since the API started. Links are never stored, only the website.</p>
        </div>
        {overview.errors.length === 0 ? (
          <p className="mt-4 text-sm text-ink-mute">No errors since the API started.</p>
        ) : (
          <div className="thin-scrollbar -mx-2 mt-3 max-h-80 overflow-auto">
            <table className="w-full min-w-[36rem] border-separate border-spacing-0 text-left text-[13px]">
              <thead>
                <tr className="text-xs text-ink-mute">
                  <th scope="col" className="sticky top-0 bg-[color-mix(in_oklab,var(--bg-soft)_92%,transparent)] px-2 py-2 font-medium">When</th>
                  <th scope="col" className="sticky top-0 bg-[color-mix(in_oklab,var(--bg-soft)_92%,transparent)] px-2 py-2 font-medium">Website</th>
                  <th scope="col" className="sticky top-0 bg-[color-mix(in_oklab,var(--bg-soft)_92%,transparent)] px-2 py-2 font-medium">While</th>
                  <th scope="col" className="sticky top-0 bg-[color-mix(in_oklab,var(--bg-soft)_92%,transparent)] px-2 py-2 font-medium">What happened</th>
                </tr>
              </thead>
              <tbody>
                {overview.errors.map((entry, index) => (
                  <tr key={`${entry.at}-${index}`} className="align-top">
                    <td className="whitespace-nowrap border-t border-line px-2 py-2 text-ink-mute">{formatAgo(entry.at, now / 1000)}</td>
                    <td className="border-t border-line px-2 py-2 text-ink">
                      {entry.platform ?? entry.domain}
                      {entry.platform && <span className="block font-mono text-[11px] text-ink-mute">{entry.domain}</span>}
                    </td>
                    <td className="whitespace-nowrap border-t border-line px-2 py-2 text-ink-soft">{STAGE[entry.stage] ?? entry.stage}</td>
                    <td className="border-t border-line px-2 py-2 text-ink-soft">
                      {entry.message}
                      <span className="block font-mono text-[11px] text-ink-mute">{entry.code}</span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </section>
  )
}
