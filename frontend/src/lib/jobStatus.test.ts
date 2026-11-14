import { describe, expect, it } from 'vitest'

import type { Job } from './api'
import { isWaiting, jobStatusText } from './jobStatus'

function job(patch: Partial<Job> & { progress?: Partial<Job['progress']> } = {}): Job {
  const { progress, ...rest } = patch
  return {
    id: 'job-1',
    status: 'running',
    stage: 'starting',
    stage_detail: null,
    queue_position: null,
    title: 'Clip',
    quality_label: '720p',
    container: 'mp4',
    progress: {
      percent: null, downloaded_bytes: 0, total_bytes: null, speed_bps: null, eta_seconds: null,
      part: null, parts: null, part_kind: null, ...progress,
    },
    file: null,
    error: null,
    embedded_subtitles: [],
    notices: [],
    ...rest,
  }
}

describe('a job that was just created', () => {
  // The API answers "queued, first in line" for every new job, also when a slot is free.
  const created = job({ status: 'queued', stage: 'queued', queue_position: 1 })

  it('is starting, not waiting, until a status answer says otherwise', () => {
    expect(jobStatusText(created, true)).toBe('Starting')
    expect(isWaiting(created, true)).toBe(false)
  })
  it('is waiting once a later answer still says queued', () => {
    expect(jobStatusText(created, false)).toBe('Waiting for a free slot')
    expect(isWaiting(created, false)).toBe(true)
  })
  it('is waiting at once when others are ahead of it', () => {
    const behind = job({ status: 'queued', stage: 'queued', queue_position: 3 })
    expect(jobStatusText(behind, true)).toBe('Waiting in line (position 3)')
    expect(isWaiting(behind, true)).toBe(true)
  })
})

describe('a running job', () => {
  it('names what is being downloaded', () => {
    expect(jobStatusText(job({ stage: 'downloading' }), false)).toBe('Downloading')
    expect(jobStatusText(job({ stage: 'downloading', progress: { part_kind: 'audio' } }), false)).toBe('Downloading audio')
    expect(jobStatusText(job({ stage: 'downloading', progress: { part: 1, parts: 2, part_kind: 'video' } }), false))
      .toBe('Downloading video (part 1 of 2)')
  })
  it('names the processing step', () => {
    expect(jobStatusText(job({ stage: 'processing', stage_detail: 'merging' }), false)).toBe('Merging video and audio')
    expect(jobStatusText(job({ stage: 'processing', stage_detail: 'embedding_subtitles' }), false)).toBe('Embedding subtitles')
    expect(jobStatusText(job({ stage: 'processing', stage_detail: 'something new' }), false)).toBe('Processing the file')
  })
  it('is starting before the first progress report, and never waiting', () => {
    expect(jobStatusText(job(), false)).toBe('Starting')
    expect(isWaiting(job(), false)).toBe(false)
  })
})
