import { useCallback, useEffect, useMemo, useReducer, useRef } from 'react'

import { ApiError, api, isAbort, toApiError, type Analysis, type Job, type Quality } from '../lib/api'

/**
 * The whole download flow as one small state machine:
 *
 *   idle -> analyzing -> ready -> job (queued/running -> completed | failed | cancelled)
 *                \-> error
 *
 * Every transition is driven by a real API response; nothing is simulated.
 */
export type Phase =
  | { name: 'idle' }
  | { name: 'analyzing'; url: string; startedAt: number }
  | { name: 'error'; url: string; error: ApiError }
  | { name: 'ready'; analysis: Analysis; startError: ApiError | null; starting: boolean }
  | {
      name: 'job'
      analysis: Analysis
      job: Job
      /** When the finished file will be deleted (`Date.now()` based), if it exists. */
      expiresAt: number | null
      busy: boolean
      /** Set while status polls are failing; the job itself keeps running on the server. */
      reconnecting: boolean
    }

interface State {
  phase: Phase
  qualityId: string | null
  embedIds: string[]
}

type Action =
  | { type: 'analyze'; url: string }
  | { type: 'analyzed'; analysis: Analysis }
  | { type: 'failed'; url: string; error: ApiError }
  | { type: 'reset' }
  | { type: 'selectQuality'; id: string }
  | { type: 'toggleEmbed'; id: string }
  | { type: 'starting' }
  | { type: 'startFailed'; error: ApiError }
  | { type: 'job'; job: Job }
  | { type: 'busy'; busy: boolean }
  | { type: 'reconnecting'; reconnecting: boolean }
  | { type: 'jobGone' }
  | { type: 'backToOptions' }

const ACTIVE: ReadonlyArray<Job['status']> = ['queued', 'running']

export function isActive(job: Job): boolean {
  return ACTIVE.includes(job.status)
}

function defaultQuality(analysis: Analysis): string | null {
  const usable = analysis.qualities.filter((q) => !q.exceeds_limit)
  return (usable.find((q) => q.recommended) ?? usable[0])?.id ?? null
}

function withJob(state: State, job: Job): State {
  const phase = state.phase
  if (phase.name !== 'ready' && phase.name !== 'job') return state
  const previous = phase.name === 'job' ? phase : null
  // Keep the original deadline: recomputing it on every poll would make the countdown jitter.
  const expiresAt =
    job.status === 'completed' && job.file
      ? (previous?.job.id === job.id && previous.expiresAt) || Date.now() + job.file.expires_in * 1000
      : null
  return {
    ...state,
    phase: { name: 'job', analysis: phase.analysis, job, expiresAt, busy: previous?.busy ?? false, reconnecting: false },
  }
}

function reducer(state: State, action: Action): State {
  const { phase } = state
  switch (action.type) {
    case 'analyze':
      return { phase: { name: 'analyzing', url: action.url, startedAt: Date.now() }, qualityId: null, embedIds: [] }
    case 'analyzed':
      return {
        phase: { name: 'ready', analysis: action.analysis, startError: null, starting: false },
        qualityId: defaultQuality(action.analysis),
        embedIds: [],
      }
    case 'failed':
      return { phase: { name: 'error', url: action.url, error: action.error }, qualityId: null, embedIds: [] }
    case 'reset':
      return { phase: { name: 'idle' }, qualityId: null, embedIds: [] }
    case 'selectQuality': {
      if (phase.name !== 'ready') return state
      const quality = phase.analysis.qualities.find((q) => q.id === action.id)
      if (!quality || quality.exceeds_limit) return state
      // Subtitles can't be embedded into every format; drop the choice when it no longer applies.
      return { ...state, qualityId: action.id, embedIds: quality.can_embed_subtitles ? state.embedIds : [] }
    }
    case 'toggleEmbed': {
      if (phase.name !== 'ready') return state
      const has = state.embedIds.includes(action.id)
      return { ...state, embedIds: has ? state.embedIds.filter((id) => id !== action.id) : [...state.embedIds, action.id] }
    }
    case 'starting':
      return phase.name === 'ready' ? { ...state, phase: { ...phase, starting: true, startError: null } } : state
    case 'startFailed':
      return phase.name === 'ready' ? { ...state, phase: { ...phase, starting: false, startError: action.error } } : state
    case 'job':
      return withJob(state, action.job)
    case 'busy':
      return phase.name === 'job' ? { ...state, phase: { ...phase, busy: action.busy } } : state
    case 'reconnecting':
      return phase.name === 'job' ? { ...state, phase: { ...phase, reconnecting: action.reconnecting } } : state
    case 'jobGone': {
      if (phase.name !== 'job') return state
      const error = { code: 'job_not_found', message: 'This download no longer exists on the server.', hint: 'It may have expired or the server restarted. Start it again.' }
      return { ...state, phase: { ...phase, expiresAt: null, reconnecting: false, job: { ...phase.job, status: 'failed', file: null, error } } }
    }
    case 'backToOptions':
      return phase.name === 'job' && !isActive(phase.job)
        ? { ...state, phase: { name: 'ready', analysis: phase.analysis, startError: null, starting: false } }
        : state
  }
}

const POLL_MS = 700
const POLL_HIDDEN_MS = 2500
const POLL_RETRY_MS = 3000

export interface Downloader {
  phase: Phase
  selectedQuality: Quality | null
  embedIds: string[]
  analyze: (url: string) => void
  cancelAnalyze: () => void
  reset: () => void
  selectQuality: (id: string) => void
  toggleEmbed: (id: string) => void
  start: () => void
  /** Cancel a running job, or delete a finished file right away. */
  cancel: () => void
  backToOptions: () => void
}

export function useDownloader(): Downloader {
  const [state, dispatch] = useReducer(reducer, { phase: { name: 'idle' }, qualityId: null, embedIds: [] })
  const analyzeAbort = useRef<AbortController | null>(null)
  // Latest state for event handlers, which must not be re-created on every update.
  const stateRef = useRef(state)
  useEffect(() => {
    stateRef.current = state
  }, [state])

  const analyze = useCallback((url: string) => {
    analyzeAbort.current?.abort()
    const controller = new AbortController()
    analyzeAbort.current = controller
    dispatch({ type: 'analyze', url })
    api
      .analyze(url, controller.signal)
      .then((analysis) => {
        if (!controller.signal.aborted) dispatch({ type: 'analyzed', analysis })
      })
      .catch((error: unknown) => {
        if (isAbort(error) || controller.signal.aborted) return
        dispatch({ type: 'failed', url, error: toApiError(error) })
      })
  }, [])

  const cancelAnalyze = useCallback(() => {
    analyzeAbort.current?.abort()
    dispatch({ type: 'reset' })
  }, [])

  const reset = useCallback(() => {
    analyzeAbort.current?.abort()
    const { phase } = stateRef.current
    // Leaving a job behind? Stop it (or delete its file) rather than abandon it on the server.
    if (phase.name === 'job' && (isActive(phase.job) || phase.job.status === 'completed')) {
      void api.cancelJob(phase.job.id).catch(() => undefined)
    }
    dispatch({ type: 'reset' })
  }, [])

  const start = useCallback(() => {
    const { phase, qualityId, embedIds } = stateRef.current
    if (phase.name !== 'ready' || phase.starting || !qualityId) return
    dispatch({ type: 'starting' })
    api
      .createJob(phase.analysis.id, qualityId, embedIds)
      .then((job) => dispatch({ type: 'job', job }))
      .catch((error: unknown) => dispatch({ type: 'startFailed', error: toApiError(error) }))
  }, [])

  const cancel = useCallback(() => {
    const { phase } = stateRef.current
    if (phase.name !== 'job' || phase.busy) return
    dispatch({ type: 'busy', busy: true })
    api
      .cancelJob(phase.job.id)
      .then((job) => dispatch({ type: 'job', job }))
      .catch((error: unknown) => {
        if (toApiError(error).code === 'job_not_found') dispatch({ type: 'jobGone' })
      })
      .finally(() => dispatch({ type: 'busy', busy: false }))
  }, [])

  // Poll while the job is queued or running. One request at a time; slower in background tabs.
  const phase = state.phase
  const pollingId = phase.name === 'job' && isActive(phase.job) ? phase.job.id : null
  useEffect(() => {
    if (!pollingId) return
    const controller = new AbortController()
    let timer: number | undefined

    const schedule = (ms: number) => {
      timer = window.setTimeout(tick, ms)
    }
    const tick = async () => {
      try {
        const job = await api.job(pollingId, controller.signal)
        if (controller.signal.aborted) return
        dispatch({ type: 'job', job })
        if (isActive(job)) schedule(document.hidden ? POLL_HIDDEN_MS : POLL_MS)
      } catch (error) {
        if (isAbort(error) || controller.signal.aborted) return
        const apiError = toApiError(error)
        if (apiError.code === 'job_not_found') {
          dispatch({ type: 'jobGone' })
          return
        }
        dispatch({ type: 'reconnecting', reconnecting: true })
        schedule(apiError.retryAfter ? apiError.retryAfter * 1000 : POLL_RETRY_MS)
      }
    }
    schedule(POLL_MS)
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [pollingId])

  // When the countdown runs out, ask the server what happened to the file.
  const expiresAt = phase.name === 'job' ? phase.expiresAt : null
  const finishedId = phase.name === 'job' && phase.job.status === 'completed' ? phase.job.id : null
  useEffect(() => {
    if (!finishedId || expiresAt === null) return
    const controller = new AbortController()
    let timer: number | undefined
    const check = () => {
      api
        .job(finishedId, controller.signal)
        .then((job) => {
          dispatch({ type: 'job', job })
          if (job.status === 'completed') timer = window.setTimeout(check, 5000)
        })
        .catch((error: unknown) => {
          if (!isAbort(error) && toApiError(error).code === 'job_not_found') dispatch({ type: 'jobGone' })
        })
    }
    timer = window.setTimeout(check, Math.max(1000, expiresAt - Date.now() + 1500))
    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [finishedId, expiresAt])

  const selectedQuality = useMemo(() => {
    const analysis = phase.name === 'ready' || phase.name === 'job' ? phase.analysis : null
    return analysis?.qualities.find((q) => q.id === state.qualityId) ?? null
  }, [phase, state.qualityId])

  return {
    phase,
    selectedQuality,
    embedIds: state.embedIds,
    analyze,
    cancelAnalyze,
    reset,
    selectQuality: useCallback((id: string) => dispatch({ type: 'selectQuality', id }), []),
    toggleEmbed: useCallback((id: string) => dispatch({ type: 'toggleEmbed', id }), []),
    start,
    cancel,
    backToOptions: useCallback(() => dispatch({ type: 'backToOptions' }), []),
  }
}
