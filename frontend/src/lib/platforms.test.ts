import { describe, expect, it } from 'vitest'

import {
  detect,
  featured,
  hostMatches,
  hostOf,
  matchPlatform,
  platformsFromDomains,
  refusalFor,
  summarise,
  usable,
  type Platform,
  type PlatformList,
} from './platforms'

function platform(id: string, domains: string[], extra: Partial<Platform> = {}): Platform {
  return { id, name: id, domains, status: 'supported', enabled: true, note: null, region: 'global', ...extra }
}

const LIST: PlatformList = {
  mode: 'platforms',
  platforms: [
    platform('YouTube', ['youtube.com', 'youtu.be'], { status: 'partial', note: 'Public videos.' }),
    platform('Pinterest', ['pinterest.*', 'pin.it'], { status: 'partial' }),
    platform('Naver TV', ['tv.naver.com']),
    platform('Dailymotion', ['dailymotion.com', 'dai.ly']),
    platform('TikTok', ['tiktok.com'], { enabled: false }),
    platform('Netflix', ['netflix.com'], { status: 'unsupported', enabled: false, note: 'Protected with DRM.' }),
  ],
}

describe('hostOf', () => {
  it('reads the host from links with and without a scheme', () => {
    expect(hostOf('https://WWW.YouTube.com/watch?v=1')).toBe('www.youtube.com')
    expect(hostOf('youtu.be/abc')).toBe('youtu.be')
    expect(hostOf('  m.youtube.com/watch?v=1  ')).toBe('m.youtube.com')
  })

  it('returns nothing while the text is not a link yet', () => {
    for (const text of ['', 'you', 'two words.com', 'localhost', '127.0.0.1/x', 'https://'])
      expect(hostOf(text)).toBeNull()
  })
})

describe('matching', () => {
  it('covers sub-domains, short links and country versions', () => {
    expect(hostMatches('a.b.example.com', 'example.com')).toBe(true)
    expect(hostMatches('pinterest.co.uk', 'pinterest.*')).toBe(true)
    expect(hostMatches('www.pinterest.de', 'pinterest.*')).toBe(true)
    for (const link of ['https://m.youtube.com/watch?v=1', 'youtu.be/x', 'music.youtube.com/watch'])
      expect(matchPlatform(LIST.platforms, link)?.id).toBe('YouTube')
    expect(matchPlatform(LIST.platforms, 'https://pin.it/abc')?.id).toBe('Pinterest')
    expect(matchPlatform(LIST.platforms, 'https://tv.naver.com/v/1')?.id).toBe('Naver TV')
  })

  it('does not fall for look-alikes', () => {
    expect(hostMatches('notexample.com', 'example.com')).toBe(false)
    expect(hostMatches('pinterest.evil.example.com', 'pinterest.*')).toBe(false)
    for (const link of ['notyoutube.com/watch', 'youtube.com.evil.example/x', 'naver.com/x'])
      expect(matchPlatform(LIST.platforms, link)).toBeNull()
  })
})

describe('detect', () => {
  it('names the platform, including ones that are off or impossible', () => {
    expect(detect(LIST, 'https://youtu.be/x')).toMatchObject({ kind: 'platform', platform: { id: 'YouTube' } })
    expect(detect(LIST, 'https://www.tiktok.com/@a/video/1')).toMatchObject({ platform: { enabled: false } })
    expect(detect(LIST, 'netflix.com/watch/1')).toMatchObject({ platform: { status: 'unsupported' } })
  })

  it('flags unknown websites, except where every website is tried', () => {
    expect(detect(LIST, 'https://www.example.org/v')).toEqual({ kind: 'unknown', host: 'example.org' })
    expect(detect({ ...LIST, mode: 'open' }, 'https://www.example.org/v')).toEqual({ kind: 'none' })
    expect(detect(LIST, 'not a link')).toEqual({ kind: 'none' })
    expect(detect(null, 'https://youtu.be/x')).toEqual({ kind: 'none' })
  })
})

describe('lists for display', () => {
  it('shows what can be used, best first', () => {
    expect(usable(LIST).map((p) => p.id)).toEqual(['Dailymotion', 'Naver TV', 'Pinterest', 'YouTube'])
    expect(usable(null)).toEqual([])
  })

  it('summarises long and short lists', () => {
    expect(summarise(usable(LIST), 2)).toBe('Dailymotion, Naver TV and 2 more')
    expect(summarise(usable(LIST).slice(0, 2))).toBe('Dailymotion and Naver TV')
    expect(summarise(usable(LIST).slice(0, 1))).toBe('Dailymotion')
    expect(summarise([])).toBe('')
  })

  it('builds a list for an API that only names domains', () => {
    const list = platformsFromDomains('allowlist', ['archive.org', 'example.org'])
    expect(list.platforms.map((p) => p.name)).toEqual(['Internet Archive', 'example.org'])
    expect(detect(list, 'https://archive.org/details/x')).toMatchObject({ kind: 'platform' })
    expect(detect(list, 'https://youtube.com/watch')).toEqual({ kind: 'unknown', host: 'youtube.com' })
  })
})

describe('featured', () => {
  it('puts internationally known platforms first and keeps the order of the service', () => {
    const list: PlatformList = {
      mode: 'platforms',
      platforms: [
        platform('Archive', ['archive.org'], { region: 'open' }),
        platform('Bilibili', ['bilibili.com'], { region: 'china' }),
        platform('YouTube', ['youtube.com'], { status: 'partial' }),
        platform('Vimeo', ['vimeo.com']),
        platform('Netflix', ['netflix.com'], { status: 'unsupported', enabled: false }),
        platform('TikTok', ['tiktok.com'], { enabled: false }),
      ],
    }
    expect(featured(list).map((item) => item.id)).toEqual(['YouTube', 'Vimeo', 'Bilibili', 'Archive'])
    expect(featured(null)).toEqual([])
  })
})

describe('refusalFor', () => {
  it('says why a link would be declined, in the words of the list', () => {
    expect(refusalFor(LIST, 'https://www.netflix.com/watch/1')).toEqual({
      code: 'platform_unsupported',
      message: "Netflix videos can't be downloaded.",
      hint: 'Protected with DRM.',
    })
    expect(refusalFor(LIST, 'https://www.tiktok.com/@a/video/1')?.code).toBe('platform_disabled')
    expect(refusalFor(LIST, 'https://www.example.org/video')).toMatchObject({
      code: 'domain_not_allowed',
      message: "example.org isn't a platform this service works with.",
    })
  })

  it('lets everything through that the service accepts or that is not a link yet', () => {
    for (const link of ['https://youtu.be/x', 'https://www.dailymotion.com/video/x1', '', 'not a link', 'http://127.0.0.1:8765/watch/demo'])
      expect(refusalFor(LIST, link)).toBeNull()
    expect(refusalFor(null, 'https://www.netflix.com/watch/1')).toBeNull()
  })

  it('leaves the answer to the service unless the list is exactly what it enforces', () => {
    for (const mode of ['allowlist', 'open'] as const) {
      const list: PlatformList = { ...LIST, mode }
      expect(refusalFor(list, 'https://www.netflix.com/watch/1')).toBeNull()
      expect(refusalFor(list, 'https://www.example.org/video')).toBeNull()
    }
    // an API from before the platform list: only its own answer counts
    expect(refusalFor(platformsFromDomains('allowlist', ['archive.org']), 'https://vimeo.com/1')).toBeNull()
  })
})
