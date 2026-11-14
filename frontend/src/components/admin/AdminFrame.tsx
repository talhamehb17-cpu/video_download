import { ArrowUpRight, LogOut, Moon, Sun } from 'lucide-react'
import type { ReactNode } from 'react'

import type { Theme } from '../../hooks/useTheme'
import { API_BASE } from '../../lib/api'
import { Link } from '../../lib/Link'
import { Logo } from '../layout/Logo'
import { Button } from '../ui/Button'

interface AdminFrameProps {
  theme: Theme
  onToggleTheme: () => void
  /** The signed-in administrator, when there is one. */
  email: string | null
  onSignOut: () => void
  children: ReactNode
}

/** Where admin requests go, shown so the administrator always knows which server is being changed. */
function apiHost(): string {
  if (!API_BASE) return 'this site'
  try {
    return new URL(API_BASE).host
  } catch {
    return API_BASE
  }
}

export function AdminFrame({ theme, onToggleTheme, email, onSignOut, children }: AdminFrameProps) {
  return (
    <div className="flex min-h-dvh flex-col">
      <header className="sticky top-0 z-40 border-b border-line bg-[color-mix(in_oklab,var(--bg)_82%,transparent)] backdrop-blur-xl">
        <div className="mx-auto flex h-16 max-w-6xl items-center justify-between gap-3 px-4 sm:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <Link to="/" aria-label="Lumora, back to the website" className="rounded-full">
              <Logo />
            </Link>
            <span className="rounded-full border border-violet/40 bg-violet/10 px-2.5 py-0.5 text-[11px] font-semibold uppercase tracking-[0.14em] text-violet">
              Admin
            </span>
          </div>
          <div className="flex items-center gap-1.5 sm:gap-2.5">
            {email && <span className="hidden max-w-56 truncate text-sm text-ink-mute md:inline">{email}</span>}
            <button
              type="button"
              onClick={onToggleTheme}
              aria-label={theme === 'dark' ? 'Switch to light theme' : 'Switch to dark theme'}
              className="grid size-10 place-items-center rounded-full text-ink-soft transition-colors hover:bg-glass hover:text-ink"
            >
              {theme === 'dark' ? <Moon className="size-[18px]" aria-hidden /> : <Sun className="size-[18px]" aria-hidden />}
            </button>
            {email && (
              <Button variant="glass" size="sm" onClick={onSignOut} icon={<LogOut className="size-3.5" aria-hidden />}>
                Sign out
              </Button>
            )}
          </div>
        </div>
      </header>

      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
        {children}
      </main>

      <footer className="border-t border-line">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-2 px-4 py-4 text-xs text-ink-mute sm:px-6">
          <span>
            Connected to <span className="font-mono text-ink-soft">{apiHost()}</span>
          </span>
          <Link to="/" className="inline-flex items-center gap-1 transition-colors hover:text-ink">
            Open the website <ArrowUpRight className="size-3" aria-hidden />
          </Link>
        </div>
      </footer>
    </div>
  )
}
