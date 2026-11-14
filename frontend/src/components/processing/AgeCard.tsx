import { m } from 'framer-motion'
import { ShieldCheck, ShieldX } from 'lucide-react'
import { useState } from 'react'

import { Button } from '../ui/Button'

interface AgeCardProps {
  /** The link that is for adults only. */
  url: string
  onConfirm: () => void
  onDecline: () => void
}

/**
 * The one question Lumora asks the visitor: are you 18 or older?
 *
 * It appears only when the platform says the video is for adults. A yes is remembered
 * in this browser for a few hours and sent with every request for this video; a no
 * refuses the link. Nothing else is asked, and no answer is invented on the visitor's behalf.
 */
export function AgeCard({ url, onConfirm, onDecline }: AgeCardProps) {
  // Shown for the record: which link the question is about, without the tracking bits.
  const [asked] = useState(() => {
    try {
      return new URL(url).hostname
    } catch {
      return ''
    }
  })
  return (
    <div role="alertdialog" aria-labelledby="age-question" aria-describedby="age-explanation"
         className="glass rounded-3xl border-warn/25 p-5 text-left sm:p-6">
      <div className="flex gap-4">
        <m.div
          initial={{ scale: 0.7, opacity: 0 }}
          animate={{ scale: 1, opacity: 1 }}
          transition={{ type: 'spring', stiffness: 400, damping: 22 }}
          className="grid size-11 shrink-0 place-items-center rounded-2xl border border-warn/30 bg-warn/10 text-warn"
        >
          <ShieldCheck className="size-5" aria-hidden />
        </m.div>
        <div className="min-w-0 flex-1">
          <p className="text-[13px] font-medium uppercase tracking-[0.16em] text-warn">One quick question</p>
          <h3 id="age-question" className="mt-1 font-display text-xl font-semibold tracking-tight text-ink">
            Are you 18 or older?
          </h3>
          <p id="age-explanation" className="mt-1.5 text-sm leading-relaxed text-ink-soft">
            The platform offers this video to adults only{asked ? ` (${asked})` : ''}. Confirm your age to continue.
            Your answer is kept in this browser for six hours, is sent with every request for this video, and lets
            Lumora read it for you. Lumora never signs in to an account.
          </p>
          <div className="mt-4 flex flex-wrap gap-2">
            <Button size="sm" onClick={onConfirm} icon={<ShieldCheck className="size-3.5" aria-hidden />}>
              Yes, I am 18 or older
            </Button>
            <Button variant="quiet" size="sm" onClick={onDecline} icon={<ShieldX className="size-3.5" aria-hidden />}>
              No, I&apos;m not
            </Button>
          </div>
        </div>
      </div>
    </div>
  )
}
