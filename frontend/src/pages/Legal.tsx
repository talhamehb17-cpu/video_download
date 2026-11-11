import { ArrowLeft } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

import type { ServiceConfig } from '../lib/api'
import { formatSpan } from '../lib/format'
import { Link } from '../lib/Link'
import { usePageEntry } from '../lib/router'
import { BRAND, CONTACT } from '../lib/site'

const UPDATED = '11 November 2026'

function Shell({ title, intro, children }: { title: string; intro: string; children: ReactNode }) {
  usePageEntry()
  useEffect(() => {
    const previous = document.title
    document.title = `${title} — ${BRAND}`
    return () => {
      document.title = previous
    }
  }, [title])

  return (
    <main id="main" className="mx-auto max-w-3xl px-4 pb-10 pt-32 sm:px-6 sm:pt-40">
      <Link to="/" className="inline-flex items-center gap-2 rounded-full text-sm text-ink-soft transition-colors hover:text-ink">
        <ArrowLeft className="size-4" aria-hidden />
        Back to {BRAND}
      </Link>
      <h1 className="mt-8 text-[clamp(2.25rem,6vw,3.5rem)] font-semibold leading-[1.05] text-ink">{title}</h1>
      <p className="mt-3 text-sm text-ink-mute">Last updated {UPDATED}</p>
      <p className="mt-6 text-lg leading-relaxed text-ink-soft">{intro}</p>
      <div className="glass mt-10 space-y-9 rounded-3xl p-6 sm:p-9">{children}</div>
    </main>
  )
}

function Block({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="text-xl font-semibold text-ink">{title}</h2>
      <div className="mt-3 space-y-3 text-[15px] leading-relaxed text-ink-soft [&_li]:pl-1 [&_strong]:font-medium [&_strong]:text-ink [&_ul]:list-disc [&_ul]:space-y-1.5 [&_ul]:pl-5">
        {children}
      </div>
    </section>
  )
}

function ContactLine() {
  return (
    <a
      href={CONTACT.href}
      className="text-cyan underline decoration-cyan/40 underline-offset-4 hover:decoration-cyan"
      {...(CONTACT.external ? { target: '_blank', rel: 'noreferrer noopener' } : {})}
    >
      {CONTACT.label}
    </a>
  )
}

export function Privacy({ config }: { config: ServiceConfig | null }) {
  const ttl = config ? formatSpan(config.limits.file_ttl_seconds) : 'a short, fixed time'
  return (
    <Shell title="Privacy Policy" intro={`${BRAND} is built to know as little about you as possible. This page explains exactly what is processed when you use it.`}>
      <Block title="No account, no tracking">
        <p>
          You never sign up or sign in. This website sets no advertising or analytics cookies and loads no third-party trackers.
          Fonts and scripts are served from this site itself.
        </p>
        <p>
          One value is stored in your browser: your light or dark theme choice (in local storage). It never leaves your device.
        </p>
      </Block>

      <Block title="What the service processes">
        <ul>
          <li>
            <strong>The link you paste.</strong> It is sent to the download service so that the video’s public information can be
            read. It is kept in memory for the life of your session and then discarded.
          </li>
          <li>
            <strong>The file you request.</strong> The service fetches it from the source and holds it temporarily so that you can
            save it.
          </li>
          <li>
            <strong>Your IP address.</strong> It is used in memory to apply fair-use limits. Logs keep only a shortened form of it
            (the last part is removed).
          </li>
        </ul>
      </Block>

      <Block title="Temporary files">
        <p>
          Prepared files are deleted automatically after {ttl}. You can delete a file sooner with “Delete now”, and cancelling a
          download removes whatever had been fetched. All temporary files are also erased whenever the service restarts.
        </p>
      </Block>

      <Block title="Logs">
        <p>
          The service keeps short technical logs to stay reliable and prevent abuse. They record the time, the type of request, its
          outcome, a shortened IP address and the name of the site a link pointed to. They do not record the full link or the title
          of the video.
        </p>
        <p>
          The companies that host this website and the download service may keep their own standard access logs, under their own
          privacy policies.
        </p>
      </Block>

      <Block title="Sources you download from">
        <p>
          To prepare a file, the service connects to the source of the video on your behalf. The source sees the service’s address,
          not yours.
        </p>
      </Block>

      <Block title="Changes and contact">
        <p>
          If this policy changes, the date at the top changes with it. Questions: <ContactLine />.
        </p>
      </Block>
    </Shell>
  )
}

export function Terms() {
  return (
    <Shell title="Terms of Use" intro={`By using ${BRAND} you agree to these terms. They are short, and they exist to keep the service lawful and fair for everyone.`}>
      <Block title="What the service does">
        <p>
          {BRAND} reads the public information of a video link you provide and prepares a copy for you to save, in a quality and
          with subtitles that the source itself offers.
        </p>
      </Block>

      <Block title="What you may download">
        <p>Use {BRAND} only for content you have the right to download, for example:</p>
        <ul>
          <li>your own videos;</li>
          <li>works in the public domain or under a licence that permits copying;</li>
          <li>content whose owner or platform allows downloading.</li>
        </ul>
        <p>You are responsible for complying with copyright law and with the terms of the source you download from.</p>
      </Block>

      <Block title="What the service will not do">
        <p>
          {BRAND} does not sign in to accounts and does not bypass DRM, paywalls, age checks, regional restrictions or other access
          controls. Private, protected and restricted content is refused. Please do not try to make it do otherwise.
        </p>
      </Block>

      <Block title="Fair use">
        <ul>
          <li>Requests are rate-limited, and file size and length are capped.</li>
          <li>Automated or bulk use, and attempts to disrupt or probe the service, are not permitted.</li>
          <li>The operator may limit or block use that puts the service or third parties at risk.</li>
        </ul>
      </Block>

      <Block title="No warranty">
        <p>
          The service is provided as is, without guarantees of availability or fitness for a particular purpose. Sources change
          and links can stop working. To the extent the law allows, the operator is not liable for losses arising from your use of
          the service or of anything you download with it.
        </p>
      </Block>

      <Block title="Rights holders">
        <p>
          {BRAND} hosts no library of content: files exist only temporarily, at a user’s request. If you believe the service is
          being used to infringe your rights, contact us and the source can be blocked: <ContactLine />.
        </p>
      </Block>
    </Shell>
  )
}

export function NotFound() {
  usePageEntry()
  useEffect(() => {
    const previous = document.title
    document.title = `Page not found — ${BRAND}`
    return () => {
      document.title = previous
    }
  }, [])
  return (
    <main id="main" className="mx-auto grid min-h-[70dvh] max-w-xl place-items-center px-4 pt-32 text-center sm:px-6">
      <div>
        <p className="text-gradient font-serif text-8xl italic">404</p>
        <h1 className="mt-4 text-3xl font-semibold text-ink">This page doesn’t exist</h1>
        <p className="mt-3 text-ink-soft">The address may be mistyped, or the page may have moved.</p>
        <Link to="/" className="bg-brand mt-8 inline-flex h-11 items-center rounded-full px-6 text-sm font-medium text-white shadow-glow">
          Back to {BRAND}
        </Link>
      </div>
    </main>
  )
}
