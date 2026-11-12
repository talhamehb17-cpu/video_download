/** What the server is doing with a download right now, in plain words. */

import type { Job } from './api'

const PROCESSING_TEXT: Record<string, string> = {
  merging: 'Merging video and audio',
  embedding_subtitles: 'Embedding subtitles',
  converting_subtitles: 'Converting subtitles',
  optimizing: 'Finalizing the file',
}

/**
 * Is the job held back because every download slot is taken?
 *
 * Every job is created as "queued, first in line" and is handed a slot a moment
 * later when one is free. So the answer to the request that created it (`fresh`)
 * looks the same whether or not there is a wait. The next status answer tells.
 */
export function isWaiting(job: Job, fresh: boolean): boolean {
  if (job.status !== 'queued') return false
  return !fresh || (job.queue_position ?? 1) > 1
}

export function jobStatusText(job: Job, fresh: boolean): string {
  if (job.status === 'queued') {
    if (!isWaiting(job, fresh)) return 'Starting'
    return job.queue_position && job.queue_position > 1 ? `Waiting in line (position ${job.queue_position})` : 'Waiting for a free slot'
  }
  if (job.stage === 'downloading') {
    const { part, parts, part_kind: kind } = job.progress
    const what = kind === 'video' ? 'Downloading video' : kind === 'audio' ? 'Downloading audio' : 'Downloading'
    return parts && parts > 1 && part ? `${what} (part ${part} of ${parts})` : what
  }
  if (job.stage === 'processing') return PROCESSING_TEXT[job.stage_detail ?? ''] ?? 'Processing the file'
  return 'Starting'
}
