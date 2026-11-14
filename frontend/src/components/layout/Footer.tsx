import { ArrowUpRight } from 'lucide-react'

import { Link } from '../../lib/Link'
import { BRAND, CONTACT, NAV_LINKS, REPOSITORY_URL } from '../../lib/site'
import { Logo } from './Logo'

const YEAR = new Date().getFullYear()

export function Footer() {
  return (
    <footer className="relative mt-24 border-t border-line">
      <div aria-hidden className="absolute inset-x-0 -top-px mx-auto h-px max-w-3xl bg-linear-to-r from-transparent via-violet/60 to-transparent" />
      <div className="mx-auto grid max-w-6xl gap-10 px-4 py-14 sm:px-6 md:grid-cols-[1.4fr_1fr_1fr]">
        <div>
          <Link to="/#top" aria-label={`${BRAND}, home`} className="inline-flex rounded-full">
            <Logo />
          </Link>
          <p className="mt-4 max-w-sm text-sm leading-relaxed text-ink-mute">
            Download public videos in the quality you choose, with subtitles. {BRAND} only processes content that is
            publicly accessible and that the source permits downloading.
          </p>
        </div>

        <nav aria-label="Footer">
          <h2 className="font-sans text-xs font-semibold uppercase tracking-[0.18em] text-ink-mute">Explore</h2>
          <ul className="mt-3 space-y-0.5 text-sm">
            {NAV_LINKS.map((link) => (
              <li key={link.id}>
                <Link to={link.to} className="inline-flex min-h-8 items-center text-ink-soft transition-colors hover:text-ink">
                  {link.label}
                </Link>
              </li>
            ))}
          </ul>
        </nav>

        <nav aria-label="Legal and contact">
          <h2 className="font-sans text-xs font-semibold uppercase tracking-[0.18em] text-ink-mute">Company</h2>
          <ul className="mt-3 space-y-0.5 text-sm">
            <li>
              <Link to="/privacy" className="inline-flex min-h-8 items-center text-ink-soft transition-colors hover:text-ink">
                Privacy Policy
              </Link>
            </li>
            <li>
              <Link to="/terms" className="inline-flex min-h-8 items-center text-ink-soft transition-colors hover:text-ink">
                Terms
              </Link>
            </li>
            <li>
              <a
                href={CONTACT.href}
                className="inline-flex min-h-8 items-center gap-1 text-ink-soft transition-colors hover:text-ink"
                {...(CONTACT.external ? { target: '_blank', rel: 'noreferrer noopener' } : {})}
              >
                Contact
                {CONTACT.external && <ArrowUpRight className="size-3.5" aria-hidden />}
              </a>
            </li>
            <li>
              <a
                href={REPOSITORY_URL}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex min-h-8 items-center gap-1 text-ink-soft transition-colors hover:text-ink"
              >
                Source code
                <ArrowUpRight className="size-3.5" aria-hidden />
              </a>
            </li>
          </ul>
        </nav>
      </div>

      <div className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-col gap-2 px-4 py-6 text-xs text-ink-mute sm:flex-row sm:items-center sm:justify-between sm:px-6">
          <p>
            © {YEAR} {BRAND}. All rights reserved.
          </p>
          <p>No accounts. No tracking. Files are deleted automatically.</p>
        </div>
      </div>
    </footer>
  )
}
