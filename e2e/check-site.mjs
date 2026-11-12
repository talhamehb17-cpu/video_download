#!/usr/bin/env node
/**
 * End-to-end check of a deployed Lumora website, in a real browser.
 *
 * Opens the site the way a visitor does and waits for the download service to
 * come online. Then, for each example link the service offers (or each --link):
 * analyzes it, picks the smallest quality, saves a subtitle track, has the file
 * prepared, saves it through the browser and deletes it from the server again.
 * Nothing is mocked: every step goes through the site's security headers, the
 * API's cross-origin rules and the real sources.
 *
 *   npm ci
 *   node check-site.mjs https://lumora-video.vercel.app
 *   node check-site.mjs https://lumora-video.vercel.app --link https://archive.org/details/SomeItem
 *
 * Options:  --link <url>   check this link instead of the example links (repeatable)
 *           --max-mb <n>   skip downloads larger than this (default 400)
 *           --out <dir>    keep screenshots of what the browser showed
 *
 * Needs Chrome or Chromium. Set CHROME_PATH when it is not in a usual place;
 * CHROME_ARGS adds launch arguments and CHROME_HEADLESS=shell selects the
 * headless-shell mode of stripped-down builds.
 */

import { appendFileSync, closeSync, existsSync, mkdirSync, mkdtempSync, openSync, readFileSync, readSync, rmSync, statSync } from 'node:fs'
import { tmpdir } from 'node:os'
import path from 'node:path'
import process from 'node:process'
import { parseArgs } from 'node:util'

import puppeteer from 'puppeteer-core'

const SERVICE_TIMEOUT = 150_000 // the site itself gives up after two minutes
const ANALYZE_TIMEOUT = 120_000
const SUBTITLE_TIMEOUT = 120_000
const JOB_TIMEOUT = 15 * 60_000
const SAVE_TIMEOUT = 10 * 60_000
/** A link no source policy with an allow list accepts. It is never fetched. */
const OUTSIDE_LINK = 'https://example.com/watch?v=lumora-check'

const USAGE = `Usage: node check-site.mjs <site address> [--link <url>]... [--max-mb <n>] [--out <dir>]

Opens the site in a real browser and downloads a video through it.
  --link <url>   check this link instead of the example links the service offers (repeatable)
  --max-mb <n>   skip downloads larger than this (default 400)
  --out <dir>    keep screenshots of what the browser showed
The address can also come from SITE_URL. Set CHROME_PATH when Chrome is not in a usual place.`

const BROWSER_PATHS = [
  '/usr/bin/google-chrome',
  '/usr/bin/google-chrome-stable',
  '/usr/bin/chromium',
  '/usr/bin/chromium-browser',
  '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
  'C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe',
  'C:\\Program Files (x86)\\Google\\Chrome\\Application\\chrome.exe',
]

// ------------------------------------------------------------------------- small helpers
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms))
const seconds = (since) => `${((Date.now() - since) / 1000).toFixed(1)} s`
const megabytes = (bytes) => `${(bytes / 1e6).toFixed(1)} MB`
const squash = (text) => (text ?? '').replace(/\s+/g, ' ').trim()

function span(totalSeconds) {
  if (totalSeconds < 90) return `${Math.round(totalSeconds)} s`
  if (totalSeconds < 5400) return `${Math.round(totalSeconds / 60)} min`
  return `${(totalSeconds / 3600).toFixed(1)} h`
}

/** What an API error answer says, in one line. */
function apiError(status, body) {
  const error = body?.error
  if (!error) return `HTTP ${status}`
  return `${error.message}${error.hint ? ` ${error.hint}` : ''} (${error.code}, HTTP ${status})`
}

/** Does the file start the way its container format should? null = format not known here. */
function looksLike(file, container) {
  const bytes = Buffer.alloc(12)
  const handle = openSync(file, 'r')
  try {
    readSync(handle, bytes, 0, 12, 0)
  } finally {
    closeSync(handle)
  }
  const text = (from, to) => bytes.subarray(from, to).toString('latin1')
  const checks = {
    mp4: () => text(4, 8) === 'ftyp',
    m4a: () => text(4, 8) === 'ftyp',
    mov: () => ['ftyp', 'moov', 'wide', 'free', 'mdat'].includes(text(4, 8)),
    webm: () => bytes.readUInt32BE(0) === 0x1a45dfa3,
    mkv: () => bytes.readUInt32BE(0) === 0x1a45dfa3,
    ogv: () => text(0, 4) === 'OggS',
    ogg: () => text(0, 4) === 'OggS',
    opus: () => text(0, 4) === 'OggS',
    avi: () => text(0, 4) === 'RIFF',
    wav: () => text(0, 4) === 'RIFF',
    flv: () => text(0, 3) === 'FLV',
    mp3: () => text(0, 3) === 'ID3' || (bytes[0] === 0xff && (bytes[1] & 0xe0) === 0xe0),
  }
  const check = checks[container?.toLowerCase()]
  return check ? check() : null
}

// ------------------------------------------------------------------------------- browser
function findBrowser() {
  const candidates = [process.env.CHROME_PATH, process.env.CHROME_BIN, ...BROWSER_PATHS]
  const found = candidates.find((candidate) => candidate && existsSync(candidate))
  if (!found) {
    throw new Error('No Chrome or Chromium found. Install one, or set CHROME_PATH to its executable.')
  }
  return found
}

async function launch() {
  const extra = (process.env.CHROME_ARGS ?? '').split(/\s+/).filter(Boolean)
  return puppeteer.launch({
    executablePath: findBrowser(),
    headless: process.env.CHROME_HEADLESS === 'shell' ? 'shell' : true,
    // Hosted CI runners do not allow Chrome's own sandbox. The only page opened is the site under test.
    args: [...(process.env.CI ? ['--no-sandbox'] : []), ...extra],
  })
}

/** Lets the browser save files into `directory` and reports each one as it completes. */
async function watchDownloads(browser, directory) {
  const session = await browser.target().createCDPSession()
  await session.send('Browser.setDownloadBehavior', { behavior: 'allowAndName', downloadPath: directory, eventsEnabled: true })
  const downloads = new Map()
  session.on('Browser.downloadWillBegin', (event) => {
    downloads.set(event.guid, { guid: event.guid, name: event.suggestedFilename, state: 'inProgress' })
  })
  session.on('Browser.downloadProgress', (event) => {
    const download = downloads.get(event.guid)
    if (download) download.state = event.state
  })

  /** Runs `action` and returns the file the browser saved because of it. */
  return async function saved(action, timeout) {
    const before = new Set(downloads.keys())
    await action()
    const deadline = Date.now() + timeout
    while (Date.now() < deadline) {
      const download = [...downloads.values()].find((item) => !before.has(item.guid))
      if (download?.state === 'completed') {
        const file = path.join(directory, download.guid)
        return { name: download.name, file, size: statSync(file).size }
      }
      if (download?.state === 'canceled') throw new Error(`the browser cancelled the download of "${download.name}"`)
      await sleep(200)
    }
    throw new Error(`the browser saved nothing within ${Math.round(timeout / 1000)} s`)
  }
}

// ---------------------------------------------------------------------------------- page
const areaText = (page) => page.$eval('#download', (node) => node.textContent).then(squash, () => '')

async function clickText(page, selector, text, { exact = false } = {}) {
  const handle = await page.evaluateHandle(
    (selector, text, exact) => {
      const clean = (node) => node.textContent.replace(/\s+/g, ' ').trim()
      const matches = [...document.querySelectorAll(selector)].filter((node) => (exact ? clean(node) === text : clean(node).includes(text)))
      return matches.at(-1) ?? null
    },
    selector,
    text,
    exact,
  )
  const element = handle.asElement()
  if (!element) throw new Error(`"${text}" is not on the page`)
  await element.click()
  await element.dispose()
}

async function enterLink(page, link) {
  await page.$eval('input[name=url]', (input) => {
    input.focus()
    input.select()
  })
  await page.keyboard.press('Backspace')
  await page.keyboard.type(link)
  await page.keyboard.press('Enter')
}

/** The next answer of the API to `method /api/v1<suffix>`, or null when none arrives. */
function nextAnswer(page, method, suffix, timeout) {
  return page
    .waitForResponse(
      (response) => response.request().method() === method && new URL(response.url()).pathname.endsWith(`/api/v1${suffix}`),
      { timeout },
    )
    .catch(() => null)
}

/** Sends the link and returns the API's answer; fails early when the page reports a network error. */
async function analyze(page, link) {
  const answer = nextAnswer(page, 'POST', '/analyze', ANALYZE_TIMEOUT)
  const alert = page.waitForSelector('#download [role=alert]', { timeout: ANALYZE_TIMEOUT }).then(
    () => 'alert',
    () => null,
  )
  await enterLink(page, link)
  const first = await Promise.race([answer, alert])
  if (first === 'alert') {
    // The page gave up without an answer from the API: let a just-arriving answer win, else report the page's words.
    const late = await Promise.race([answer, sleep(1500).then(() => null)])
    if (!late) throw new Error(`the page reported: ${await areaText(page)}`)
    return { status: late.status(), body: await late.json().catch(() => null) }
  }
  if (!first) throw new Error(`no answer from the API within ${ANALYZE_TIMEOUT / 1000} s`)
  return { status: first.status(), body: await first.json().catch(() => null) }
}

const cleared = (page) => page.waitForFunction(() => !document.querySelector('#download')?.firstElementChild, { timeout: 10_000 })

async function startOver(page) {
  await clickText(page, '#download button', 'Use another link')
  await cleared(page)
}

// ---------------------------------------------------------------------------- the checks
async function checkService(ctx) {
  const { page, site } = ctx
  const started = Date.now()
  await page.goto(site.href, { waitUntil: 'domcontentloaded', timeout: 60_000 })

  // The pill above the headline is what a visitor sees; wait until it has made up its mind.
  const pill = await page
    .waitForFunction(
      () => {
        const text = document.querySelector('[role=status] span:not([aria-hidden])')?.textContent.trim() ?? ''
        return /^(Service online|Download service)/.test(text) ? text : false
      },
      { timeout: SERVICE_TIMEOUT },
    )
    .then((handle) => handle.jsonValue())
    .catch(() => null)

  const title = await page.title()
  if (!pill) {
    const shown = await page.$eval('[role=status]', (node) => node.textContent).catch(() => 'no status at all')
    return ctx.fail('Service', `after ${SERVICE_TIMEOUT / 1000} s the site still had not said whether the service is there (it shows: ${squash(shown)})`)
  }
  if (pill.includes('not connected')) {
    return ctx.fail('Service', 'the site was built without the address of an API: set VITE_API_BASE_URL in the website host and redeploy')
  }
  if (!pill.startsWith('Service online')) {
    const why = ctx.apiOrigin ? await describeApi(ctx.apiOrigin, site.origin).catch((error) => `asking it directly failed: ${error.message}`) : 'the page made no request to an API'
    return ctx.fail('Service', `the site says "${pill}". ${why}`)
  }
  for (let waited = 0; !ctx.config && waited < 5000; waited += 100) await sleep(100) // our copy of the answer arrives a moment later
  if (!ctx.config) return ctx.fail('Service', 'the site says it is online, but no configuration answer was seen')

  const { config } = ctx
  const policy = config.sources.mode === 'allowlist' ? `${config.sources.domains.length} sources on the allow list` : 'every supported source'
  const direct = await describeApi(ctx.apiOrigin, site.origin).catch((error) => `asking it directly failed: ${error.message}`)
  // The name of the main script changes with every build of the site, so it tells deployments apart.
  const build = await page.$eval('script[type=module][src]', (script) => script.src.split('/').pop().replace(/\.js$/, '')).catch(() => 'unknown')
  ctx.pass(
    'Service',
    `${site.origin} ("${title}", build ${build}) says "${pill}" after ${seconds(started)}. API ${ctx.apiOrigin}: ${config.name} ${config.version}, ${policy}, ` +
      `files up to ${megabytes(config.limits.max_file_size_bytes)} kept for ${span(config.limits.file_ttl_seconds)}. ${direct}`,
  )
  return true
}

/** Asks the API directly, as the site's origin, and says what answered. */
async function describeApi(apiOrigin, siteOrigin) {
  const response = await fetch(`${apiOrigin}/api/v1/health`, { headers: { Origin: siteOrigin }, signal: AbortSignal.timeout(20_000) })
  const health = await response.json().catch(() => null)
  const allowed = response.headers.get('access-control-allow-origin')
  const parts = [`Asked directly: HTTP ${response.status}`]
  if (health?.status) parts.push(`status ${health.status}`, health.ffmpeg ? 'FFmpeg present' : 'FFMPEG MISSING', `up ${span(health.uptime_seconds)}`)
  if (apiOrigin !== siteOrigin) {
    parts.push(allowed === siteOrigin || allowed === '*' ? `accepts requests from ${siteOrigin}` : `DOES NOT accept requests from ${siteOrigin} (add it to ALLOWED_ORIGINS on the API)`)
  }
  const server = [response.headers.get('server'), response.headers.get('via')].filter(Boolean).join(', ')
  if (server) parts.push(`served through ${server}`)
  return `${parts.join(', ')}.`
}

/** With an allow list, a link from elsewhere must be declined, in words, without a pointless "Try again". */
async function checkRefusal(ctx) {
  const { page } = ctx
  const { status, body } = await analyze(page, OUTSIDE_LINK)
  await page.waitForSelector('#download [role=alert]', { timeout: 15_000 })
  const shown = squash(await page.$eval('#download [role=alert] p', (node) => node.textContent))
  const retry = await page.$$eval('#download button', (buttons) => buttons.some((button) => button.textContent.includes('Try again')))
  const declined = status === 422 && body?.error?.code === 'domain_not_allowed'
  const details = `${OUTSIDE_LINK} -> "${shown}" (${body?.error?.code ?? `HTTP ${status}`})${retry ? ', but "Try again" is offered' : ', no "Try again" offered'}`
  if (declined && !retry) ctx.pass('Link outside the allow list', details)
  else ctx.fail('Link outside the allow list', details)
  await startOver(page)
}

async function checkLink(ctx, link, label) {
  const { page, saved } = ctx

  // ------------------------------------------------------------------------- analyze
  let started = Date.now()
  const { status, body: analysis } = await analyze(page, link)
  if (status !== 200) return ctx.fail(`${label}: analyze`, apiError(status, analysis))
  await page.waitForSelector('#download fieldset input[type=radio]', { timeout: 20_000 })
  const analyzed = seconds(started)

  let poster = 'no poster at the source'
  if (analysis.thumbnail_url) {
    const loaded = await page
      .waitForFunction(() => { const image = document.querySelector('#download img'); return image ? image.complete && image.naturalWidth > 0 : false }, { timeout: 20_000 })
      .then(() => true, () => false)
    poster = loaded ? 'poster shown' : 'POSTER NOT SHOWN'
  }
  const qualities = analysis.qualities.map((quality) => `${quality.label} ${quality.container}`).join(', ')
  const summary = `"${analysis.title}" from ${analysis.source.domain} in ${analyzed}: ${qualities}; ${analysis.subtitles.length} subtitle language(s); ${poster}`
  await ctx.shot(`${label} result`)
  if (poster === 'POSTER NOT SHOWN') ctx.fail(`${label}: analyze`, summary)
  else ctx.pass(`${label}: analyze`, summary)

  // ------------------------------------------------------------------------ subtitles
  if (analysis.subtitles.length > 0) {
    const track = analysis.subtitles[0]
    started = Date.now()
    try {
      const failure = page.waitForSelector('#download section li [role=alert]', { timeout: SUBTITLE_TIMEOUT }).then(
        async (node) => { throw new Error(squash(await node.evaluate((element) => element.textContent))) },
        () => new Promise(() => {}),
      )
      const subtitle = await Promise.race([
        saved(async () => {
          const button = await page.$('#download section li button[aria-label$="as SRT"]')
          if (!button) throw new Error('no SRT button on the page')
          await button.click()
        }, SUBTITLE_TIMEOUT),
        failure,
      ])
      const text = readFileSync(subtitle.file, 'utf8')
      const cues = text.split('-->').length - 1
      if (cues > 0) ctx.pass(`${label}: subtitles`, `${track.language} saved as "${subtitle.name}", ${cues} cues, in ${seconds(started)}`)
      else ctx.fail(`${label}: subtitles`, `"${subtitle.name}" is not an SRT file (${subtitle.size} bytes)`)
    } catch (error) {
      ctx.fail(`${label}: subtitles`, `${track.language} as SRT: ${error.message}`)
    }
  }

  // ------------------------------------------------------------------------- download
  const allowed = analysis.qualities.filter((quality) => !quality.exceeds_limit)
  if (allowed.length === 0) return ctx.fail(`${label}: download`, 'every quality is over the service\'s size limit')
  const sized = allowed.filter((quality) => quality.filesize)
  // The smallest file keeps the check light on the source; without sizes, the last option is the lowest quality.
  const quality = sized.length > 0 ? sized.reduce((a, b) => (b.filesize < a.filesize ? b : a)) : allowed.at(-1)
  if (quality.filesize && quality.filesize > ctx.maxBytes) {
    ctx.pass(`${label}: download`, `skipped, the smallest option is ${megabytes(quality.filesize)}`)
    await page.click('#download button[aria-label="Close and start over"]')
    await cleared(page)
    return undefined
  }

  const tile = await page.evaluateHandle(
    (id) => [...document.querySelectorAll('#download fieldset input[type=radio]')].find((input) => input.value === id)?.closest('label') ?? null,
    quality.id,
  )
  if (!tile.asElement()) return ctx.fail(`${label}: download`, `the page does not show the quality ${quality.label} ${quality.container}`)
  await tile.asElement().click()

  // Put the first subtitle track inside the file when the format can carry one: that runs FFmpeg on the server.
  let embedding = null
  if (quality.can_embed_subtitles) {
    const track = analysis.subtitles.find((item) => item.embeddable)
    const toggle = track && (await page.$('#download section li label:has(input[type=checkbox])'))
    if (toggle) {
      await toggle.click()
      if (await toggle.$eval('input', (input) => input.checked)) embedding = track.language
    }
  }

  started = Date.now()
  const created = nextAnswer(page, 'POST', '/jobs', 60_000)
  await clickText(page, '#download button', 'Download', { exact: true })
  const answer = await created
  if (!answer) return ctx.fail(`${label}: download`, `the API did not answer the request to start. The page shows: ${await areaText(page)}`)
  if (answer.status() !== 202) return ctx.fail(`${label}: download`, apiError(answer.status(), await answer.json().catch(() => null)))
  const jobId = (await answer.json()).id

  const seen = []
  let state
  while (Date.now() - started < JOB_TIMEOUT) {
    state = await page.evaluate(() => {
      const area = document.querySelector('#download')
      const save = [...area.querySelectorAll('a')].find((link) => link.textContent.includes('Save file'))
      if (save) return { name: 'ready', href: save.href }
      const alert = area.querySelector('[role=alert]')
      if (alert) return { name: 'failed', text: alert.textContent }
      const bar = area.querySelector('[role=progressbar]')
      return { name: 'working', step: bar?.getAttribute('aria-valuenow') ? `${bar.getAttribute('aria-valuenow')}%` : bar?.getAttribute('aria-label') }
    })
    if (state.name !== 'working') break
    if (state.step && seen.at(-1) !== state.step) seen.push(state.step)
    await sleep(400)
  }
  if (state.name === 'failed') return ctx.fail(`${label}: download`, `${quality.label} ${quality.container}: ${squash(state.text)}`)
  if (state.name !== 'ready') return ctx.fail(`${label}: download`, `${quality.label} ${quality.container} was not ready after ${JOB_TIMEOUT / 60_000} minutes`)
  const prepared = seconds(started)
  for (let waited = 0; ctx.jobs.get(jobId)?.status !== 'completed' && waited < 5000; waited += 100) await sleep(100)
  const job = ctx.jobs.get(jobId)
  await ctx.shot(`${label} ready`)

  started = Date.now()
  const file = await saved(() => clickText(page, '#download a', 'Save file'), SAVE_TIMEOUT)
  const problems = []
  if (job?.file && file.size !== job.file.size) problems.push(`the browser saved ${file.size} bytes, the server prepared ${job.file.size}`)
  const container = job?.file?.container ?? quality.container
  const genuine = looksLike(file.file, container)
  if (genuine === false) problems.push(`the file does not start like a ${container} file`)
  if (embedding && !job?.embedded_subtitles?.length) problems.push(`the ${embedding} subtitles were not embedded`)
  const progress = seen.length > 0 ? `progress shown: ${seen.slice(0, 12).join(' -> ')}` : 'ready before any progress could be read'
  const details =
    `${quality.label} ${container}${embedding && job?.embedded_subtitles?.length ? ` with ${embedding} subtitles embedded` : ''}, prepared in ${prepared} (${progress}); ` +
    `"${file.name}" saved by the browser in ${seconds(started)}, ${megabytes(file.size)}${genuine ? `, a genuine ${container} file` : ''}`
  rmSync(file.file, { force: true })
  if (problems.length > 0) ctx.fail(`${label}: download`, `${details}. BUT ${problems.join('; ')}`)
  else ctx.pass(`${label}: download`, details)

  // --------------------------------------------------------------------------- delete
  await clickText(page, '#download button', 'Delete now')
  const removed = await page.waitForFunction(() => document.querySelector('#download')?.textContent.includes('File deleted'), { timeout: 30_000 }).then(() => true, () => false)
  const after = await fetch(state.href, { signal: AbortSignal.timeout(20_000) }).then((response) => response.status, (error) => error.message)
  if (removed && after === 410) ctx.pass(`${label}: delete`, 'the page says "File deleted" and the file link now answers 410 Gone')
  else ctx.fail(`${label}: delete`, `page says deleted: ${removed}; the file link answers ${after}`)
  await startOver(page)
  return undefined
}

// ---------------------------------------------------------------------------------- main
async function main() {
  const { values, positionals } = parseArgs({
    allowPositionals: true,
    options: {
      link: { type: 'string', multiple: true, default: [] },
      out: { type: 'string' },
      'max-mb': { type: 'string', default: '400' },
      help: { type: 'boolean', short: 'h', default: false },
    },
  })
  const address = positionals[0] ?? process.env.SITE_URL
  if (values.help || !address) {
    console.log(USAGE)
    return values.help ? 0 : 2
  }

  const rows = []
  const downloadsDir = mkdtempSync(path.join(tmpdir(), 'lumora-check-'))
  if (values.out) mkdirSync(values.out, { recursive: true })
  const browser = await launch()
  const page = await browser.newPage()
  await page.setViewport({ width: 1366, height: 900 })

  const ctx = {
    page,
    site: new URL(address),
    saved: await watchDownloads(browser, downloadsDir),
    maxBytes: Number(values['max-mb']) * 1e6,
    apiOrigin: null,
    config: null,
    jobs: new Map(),
    problems: [],
    hosts: new Set(),
    shots: 0,
    pass: (step, details) => rows.push({ step, ok: true, details }),
    fail: (step, details) => { rows.push({ step, ok: false, details }); return false },
    shot: async (name) => {
      if (!values.out) return
      ctx.shots += 1
      const file = `${String(ctx.shots).padStart(2, '0')}-${name.toLowerCase().replace(/[^a-z0-9]+/g, '-')}.png`
      await sleep(900) // let the card finish gliding into place
      await page.screenshot({ path: path.join(values.out, file) }).catch(() => {})
    },
  }

  // Everything the page does with the API, and everything that goes wrong in the browser.
  // The answers to "analyze this link" and "start this download" are read and reported by
  // the steps themselves, so an error answer there is not counted a second time.
  const judgedByStep = (address) => /\/api\/v1\/(analyze|jobs)$/.test(new URL(address).pathname)
  page.on('request', (request) => { if (request.url().startsWith('http')) ctx.hosts.add(new URL(request.url()).host) })
  page.on('response', async (response) => {
    const url = new URL(response.url())
    const method = response.request().method()
    const status = response.status()
    if (status >= 400 && !(method === 'POST' && judgedByStep(url))) ctx.problems.push(`HTTP ${status} for ${method} ${url.origin}${url.pathname}`)
    if (method === 'OPTIONS' || !url.pathname.includes('/api/v1/') || !(response.headers()['content-type'] ?? '').includes('json')) return
    const body = await response.json().catch(() => null)
    if (!body) return
    if (url.pathname.endsWith('/api/v1/config') && status === 200) {
      ctx.apiOrigin = url.origin
      ctx.config = body
    }
    if (/\/api\/v1\/jobs(\/[^/]+)?$/.test(url.pathname) && body.id) ctx.jobs.set(body.id, body)
  })
  page.on('requestfailed', (request) => {
    const reason = request.failure()?.errorText ?? 'failed'
    const url = new URL(request.url())
    if (url.pathname.endsWith('/api/v1/config')) ctx.apiOrigin ??= url.origin
    if (reason !== 'net::ERR_ABORTED') ctx.problems.push(`${reason} for ${request.method()} ${url.origin}${url.pathname}`)
  })
  page.on('console', (message) => {
    if (message.type() !== 'error') return
    const about = message.location()?.url
    // The browser also logs every error answer; skip the ones a step reports.
    if (about?.startsWith('http') && judgedByStep(about) && message.text().includes('the server responded with a status of')) return
    ctx.problems.push(`console: ${message.text().slice(0, 300)}`)
  })
  page.on('pageerror', (error) => ctx.problems.push(`script error: ${String(error).slice(0, 300)}`))

  try {
    if (await checkService(ctx)) {
      if (ctx.config.sources.mode === 'allowlist') {
        await checkRefusal(ctx).catch((error) => ctx.fail('Link outside the allow list', error.message))
      }
      const examples = ctx.config.sources.examples
      const named = (url) => `${new URL(url).hostname}${new URL(url).pathname}`.replace(/\/$/, '').slice(0, 48)
      const links = values.link.length > 0 ? values.link.map((url) => ({ url, label: named(url) })) : examples
      if (links.length === 0) ctx.fail('Links', 'the service offers no example links: pass one with --link')
      for (const { url, label } of links) {
        const before = rows.length
        try {
          await checkLink(ctx, url, label)
        } catch (error) {
          ctx.fail(`${label}: ${rows.length === before ? 'analyze' : 'after that'}`, `${error.message}. The page shows: ${(await areaText(page)).slice(0, 300)}`)
        }
        if (rows.slice(before).some((row) => !row.ok)) {
          await ctx.shot(`${label} failed`)
          // Start the next link from a clean page.
          await page.goto(ctx.site.href, { waitUntil: 'domcontentloaded' }).catch(() => {})
          await page.waitForFunction(() => document.querySelector('[role=status]')?.textContent.trim().startsWith('Service online'), { timeout: SERVICE_TIMEOUT }).catch(() => {})
        }
      }
    } else {
      await ctx.shot('service')
    }
    const others = [...ctx.hosts].filter((host) => host !== ctx.site.host && host !== (ctx.apiOrigin && new URL(ctx.apiOrigin).host))
    const contacted = `the page contacted ${[...ctx.hosts].join(', ') || 'nothing'}${others.length > 0 ? ` (other than the site and the API: ${others.join(', ')})` : ''}`
    const problems = [...new Set(ctx.problems)]
    if (problems.length > 0) ctx.fail('Browser', `${problems.slice(0, 8).join('; ')}; ${contacted}`)
    else ctx.pass('Browser', `no failed requests, blocked content or script errors; ${contacted}`)
  } finally {
    await browser.close().catch(() => {})
    rmSync(downloadsDir, { recursive: true, force: true })
  }
  return report(ctx.site, rows)
}

function report(site, rows) {
  const ok = rows.every((row) => row.ok)
  const cell = (text) => text.replaceAll('|', '\\|').replace(/\s+/g, ' ')
  const table = ['| Step | Result | Details |', '| --- | --- | --- |', ...rows.map((row) => `| ${cell(row.step)} | ${row.ok ? 'passed' : 'FAILED'} | ${cell(row.details)} |`)].join('\n')
  console.log(table)
  console.log(ok ? `\n${site.origin} works end to end.` : `\n${site.origin} FAILED ${rows.filter((row) => !row.ok).length} of ${rows.length} checks.`)

  if (process.env.GITHUB_ACTIONS) {
    // One annotation per step, so the outcome is readable on the run page without opening the log.
    const escape = (text) => text.replaceAll('%', '%25').replaceAll('\r', ' ').replaceAll('\n', ' ')
    for (const row of rows) {
      const title = `${row.step} ${row.ok ? 'passed' : 'FAILED'}`.replaceAll(':', ' -').replaceAll(',', ' ')
      console.log(`::${row.ok ? 'notice' : 'error'} title=${escape(title)}::${escape(row.details).slice(0, 1800)}`)
    }
  }
  if (process.env.GITHUB_STEP_SUMMARY) {
    appendFileSync(process.env.GITHUB_STEP_SUMMARY, `## ${site.origin}\n\n${table}\n`)
  }
  return ok ? 0 : 1
}

main().then(
  (code) => process.exit(code),
  (error) => {
    console.error(error.message)
    if (process.env.GITHUB_ACTIONS) console.log(`::error title=Site check could not run::${error.message.replaceAll('\n', ' ')}`)
    process.exit(2)
  },
)
