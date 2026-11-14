import { BadgeCheck, CircleAlert, CircleHelp, CircleSlash, LoaderCircle, type LucideIcon } from 'lucide-react'

import type { AdminStatus } from '../../lib/adminApi'
import { ADMIN_STATUS_LABEL } from '../../lib/adminView'
import { cn } from '../../lib/cn'

const TONE: Record<AdminStatus, { className: string; Icon: LucideIcon }> = {
  supported: { className: 'border-ok/30 bg-ok/10 text-ok', Icon: BadgeCheck },
  partial: { className: 'border-warn/30 bg-warn/10 text-warn', Icon: CircleAlert },
  unsupported: { className: 'border-bad/30 bg-bad/10 text-bad', Icon: CircleSlash },
  requires_review: { className: 'border-blue/35 bg-blue/10 text-blue', Icon: CircleHelp },
}

export function StatusBadge({ status, checking = false }: { status: AdminStatus; checking?: boolean }) {
  if (checking) {
    return (
      <span className="inline-flex items-center gap-1.5 rounded-full border border-line-strong bg-glass-strong px-2.5 py-1 text-xs font-medium text-ink-soft">
        <LoaderCircle className="size-3.5 animate-spin" aria-hidden />
        Checking…
      </span>
    )
  }
  const { className, Icon } = TONE[status]
  return (
    <span data-status={status} className={cn('inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium', className)}>
      <Icon className="size-3.5" aria-hidden />
      {ADMIN_STATUS_LABEL[status]}
    </span>
  )
}
