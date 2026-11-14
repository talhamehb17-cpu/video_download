import { AnimatePresence, m } from 'framer-motion'
import { Menu, Moon, Sun, X } from 'lucide-react'
import { useEffect, useState } from 'react'

import type { Theme } from '../../hooks/useTheme'
import { cn } from '../../lib/cn'
import { Link } from '../../lib/Link'
import { NAV_LINKS } from '../../lib/site'
import { Logo } from './Logo'

interface NavbarProps {
  theme: Theme
  onToggleTheme: () => void
  /** Section currently in view on the home page (null on other pages). */
  activeSection: string | null
}

function ThemeToggle({ theme, onToggle }: { theme: Theme; onToggle: () => void }) {
  const next = theme === 'dark' ? 'light' : 'dark'
  return (
    <button
      type="button"
      onClick={onToggle}
      aria-label={`Switch to ${next} theme`}
      title={`Switch to ${next} theme`}
      className="relative grid size-10 place-items-center overflow-hidden rounded-full border border-line bg-glass text-ink-soft backdrop-blur-md transition-colors hover:border-line-strong hover:text-ink"
    >
      <AnimatePresence mode="wait" initial={false}>
        <m.span
          key={theme}
          initial={{ y: 14, opacity: 0, rotate: -60 }}
          animate={{ y: 0, opacity: 1, rotate: 0 }}
          exit={{ y: -14, opacity: 0, rotate: 60 }}
          transition={{ duration: 0.25, ease: [0.16, 1, 0.3, 1] }}
          className="grid place-items-center"
        >
          {theme === 'dark' ? <Moon className="size-[18px]" aria-hidden /> : <Sun className="size-[18px]" aria-hidden />}
        </m.span>
      </AnimatePresence>
    </button>
  )
}

export function Navbar({ theme, onToggleTheme, activeSection }: NavbarProps) {
  const [scrolled, setScrolled] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    const update = () => setScrolled(window.scrollY > 12)
    update()
    window.addEventListener('scroll', update, { passive: true })
    return () => window.removeEventListener('scroll', update)
  }, [])

  // While the mobile menu is open: Escape closes it and the page behind does not scroll.
  useEffect(() => {
    if (!open) return
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false)
    }
    const onResize = () => {
      if (window.innerWidth >= 768) setOpen(false)
    }
    document.addEventListener('keydown', onKey)
    window.addEventListener('resize', onResize)
    const previous = document.body.style.overflow
    document.body.style.overflow = 'hidden'
    return () => {
      document.removeEventListener('keydown', onKey)
      window.removeEventListener('resize', onResize)
      document.body.style.overflow = previous
    }
  }, [open])

  return (
    <header className="fixed inset-x-0 top-0 z-50">
      {/* softens whatever scrolls through the gap above the floating bar */}
      <div aria-hidden className={cn('nav-veil', (scrolled || open) && 'opacity-100')} />
      <div className="mx-auto max-w-6xl px-4 pt-3 sm:px-6">
        <nav
          aria-label="Main"
          className={cn(
            'flex h-14 items-center justify-between rounded-full border px-3 pl-4 transition-[background-color,border-color,box-shadow,backdrop-filter] duration-200',
            scrolled || open
              ? 'border-line bg-[color-mix(in_oklab,var(--bg)_72%,transparent)] shadow-panel backdrop-blur-xl'
              : 'border-transparent bg-transparent',
          )}
        >
          <Link to="/#top" aria-label="Lumora, home" className="rounded-full" onClick={() => setOpen(false)}>
            <Logo />
          </Link>

          <ul className="hidden items-center gap-1 md:flex">
            {NAV_LINKS.map((link) => {
              const active = activeSection === link.id
              return (
                <li key={link.id}>
                  <Link
                    to={link.to}
                    aria-current={active ? 'true' : undefined}
                    className={cn(
                      'relative rounded-full px-3.5 py-2 text-sm transition-colors',
                      active ? 'text-ink' : 'text-ink-soft hover:text-ink',
                    )}
                  >
                    {link.label}
                    <span
                      aria-hidden
                      className={cn(
                        'absolute inset-x-3.5 -bottom-px h-px origin-center bg-linear-to-r from-violet via-blue to-cyan transition-transform duration-300',
                        active ? 'scale-x-100' : 'scale-x-0',
                      )}
                    />
                  </Link>
                </li>
              )
            })}
          </ul>

          <div className="flex items-center gap-2">
            <ThemeToggle theme={theme} onToggle={onToggleTheme} />
            <button
              type="button"
              className="grid size-10 place-items-center rounded-full border border-line bg-glass text-ink backdrop-blur-md md:hidden"
              aria-label={open ? 'Close menu' : 'Open menu'}
              aria-expanded={open}
              aria-controls="mobile-menu"
              onClick={() => setOpen((value) => !value)}
            >
              {open ? <X className="size-[18px]" aria-hidden /> : <Menu className="size-[18px]" aria-hidden />}
            </button>
          </div>
        </nav>

        <AnimatePresence>
          {open && (
            <m.div
              id="mobile-menu"
              initial={{ opacity: 0, y: -8, scale: 0.98 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, y: -8, scale: 0.98 }}
              transition={{ duration: 0.22, ease: [0.16, 1, 0.3, 1] }}
              className="mt-2 origin-top rounded-3xl border border-line bg-[color-mix(in_oklab,var(--bg)_86%,transparent)] p-2 shadow-panel backdrop-blur-xl md:hidden"
            >
              <ul>
                {NAV_LINKS.map((link, index) => (
                  <m.li
                    key={link.id}
                    initial={{ opacity: 0, x: -10 }}
                    animate={{ opacity: 1, x: 0 }}
                    transition={{ delay: 0.04 * index + 0.05, duration: 0.25 }}
                  >
                    <Link
                      to={link.to}
                      onClick={() => setOpen(false)}
                      className={cn(
                        'flex items-center justify-between rounded-2xl px-4 py-3.5 text-base',
                        activeSection === link.id ? 'bg-glass-strong text-ink' : 'text-ink-soft hover:bg-glass hover:text-ink',
                      )}
                    >
                      {link.label}
                    </Link>
                  </m.li>
                ))}
              </ul>
            </m.div>
          )}
        </AnimatePresence>
      </div>
    </header>
  )
}
