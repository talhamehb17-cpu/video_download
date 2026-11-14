import { describe, expect, it } from 'vitest'

import { formatBytes, formatClock, formatDuration, formatEta, formatSpan, formatSpeed, hostnameOf, languageName } from './format'

describe('formatBytes', () => {
  it('scales units and precision', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(999)).toBe('999 B')
    expect(formatBytes(1536)).toBe('1.50 KB')
    expect(formatBytes(15_728_640)).toBe('15.0 MB')
    expect(formatBytes(234_600_000)).toBe('224 MB')
    expect(formatBytes(2 * 1024 ** 3)).toBe('2.00 GB')
  })
  it('trims trailing zeros for static values such as limits', () => {
    expect(formatBytes(50 * 1024 ** 2, { trim: true })).toBe('50 MB')
    expect(formatBytes(2 * 1024 ** 3, { trim: true })).toBe('2 GB')
    expect(formatBytes(1.5 * 1024 ** 3, { trim: true })).toBe('1.5 GB')
    expect(formatBytes(4_803_724, { trim: true })).toBe('4.58 MB')
    expect(formatBytes(100 * 1024 ** 2, { trim: true })).toBe('100 MB')
    expect(formatBytes(500, { trim: true })).toBe('500 B')
  })
  it('handles missing values', () => {
    expect(formatBytes(null)).toBe('—')
    expect(formatBytes(undefined)).toBe('—')
    expect(formatBytes(Number.NaN)).toBe('—')
    expect(formatBytes(-5)).toBe('—')
  })
})

describe('time formatting', () => {
  it('formats durations', () => {
    expect(formatDuration(8)).toBe('0:08')
    expect(formatDuration(75)).toBe('1:15')
    expect(formatDuration(3725)).toBe('1:02:05')
    expect(formatDuration(null)).toBeNull()
    expect(formatDuration(0)).toBeNull()
  })
  it('formats remaining time', () => {
    expect(formatEta(0.4)).toBe('almost done')
    expect(formatEta(8)).toBe('8 s left')
    expect(formatEta(95)).toBe('2 min left')
    expect(formatEta(3700)).toBe('1 h 2 min left')
    expect(formatEta(null)).toBeNull()
    expect(formatEta(-1)).toBeNull()
  })
  it('formats spans and clocks', () => {
    expect(formatSpan(60)).toBe('60 seconds')
    expect(formatSpan(900)).toBe('15 minutes')
    expect(formatSpan(1800)).toBe('30 minutes')
    expect(formatSpan(7200)).toBe('2 hours')
    expect(formatClock(754)).toBe('12:34')
    expect(formatClock(-3)).toBe('0:00')
  })
  it('formats speed', () => {
    expect(formatSpeed(3_355_443)).toBe('3.20 MB/s')
    expect(formatSpeed(0)).toBeNull()
    expect(formatSpeed(null)).toBeNull()
  })
})

describe('languageName', () => {
  it('names known languages', () => {
    expect(languageName('en')).toBe('English')
    expect(languageName('pt-BR')).toBe('Brazilian Portuguese')
    expect(languageName('en-orig')).toBe('English')
  })
  it('falls back for unknown codes', () => {
    expect(languageName('zz-not-real', 'Custom')).toBe('Custom')
    expect(languageName('???')).toBe('???')
  })
})

describe('hostnameOf', () => {
  it('extracts hosts', () => {
    expect(hostnameOf('https://archive.org/details/x')).toBe('archive.org')
    expect(hostnameOf('commons.wikimedia.org/wiki/File:x.webm')).toBe('commons.wikimedia.org')
    expect(hostnameOf('')).toBeNull()
  })
})
