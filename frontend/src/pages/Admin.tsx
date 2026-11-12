import { LoaderCircle, ServerOff, type LucideIcon, PlugZap, Wrench } from 'lucide-react'
import { useEffect, type ReactNode } from 'react'

import { AdminFrame } from '../components/admin/AdminFrame'
import { Panel } from '../components/admin/Panel'
import { PasswordForm } from '../components/admin/PasswordForm'
import { SignIn } from '../components/admin/SignIn'
import { Button } from '../components/ui/Button'
import { useAdmin, type AdminView } from '../hooks/useAdmin'
import type { Theme } from '../hooks/useTheme'
import { BRAND } from '../lib/site'

type Unavailable = Extract<AdminView, { name: 'unavailable' }>

function Code({ children }: { children: ReactNode }) {
  return <code className="rounded-md border border-line bg-glass px-1.5 py-0.5 font-mono text-[13px] text-ink">{children}</code>
}

function explain(view: Unavailable): { Icon: LucideIcon; title: string; body: ReactNode } {
  switch (view.reason) {
    case 'old_api':
      return {
        Icon: Wrench,
        title: 'The API needs an update first',
        body: (
          <>
            <p>
              The API this website is connected to runs version <Code>{view.version ?? 'unknown'}</Code>. The admin panel arrived
              with version 1.1.
            </p>
            <p>Update the API on its server and restart it. This page works as soon as the new version answers.</p>
          </>
        ),
      }
    case 'not_configured':
      return {
        Icon: PlugZap,
        title: 'The admin panel is switched off on the server',
        body: (
          <>
            <p>
              It stays off until the API is given an administrator. Set <Code>ADMIN_EMAIL</Code> and{' '}
              <Code>ADMIN_BOOTSTRAP_PASSWORD</Code> in the API’s environment and restart it.
            </p>
            <p>The initial password works only until the first sign-in, where you replace it with your own.</p>
          </>
        ),
      }
    case 'unreachable':
      return {
        Icon: ServerOff,
        title: 'The API can’t be reached',
        body: (
          <p>
            {view.error?.message ?? 'There was no answer.'} {view.error?.hint}
          </p>
        ),
      }
  }
}

function UnavailableCard({ view, onRetry }: { view: Unavailable; onRetry: () => void }) {
  const { Icon, title, body } = explain(view)
  return (
    <div className="glass mx-auto w-full max-w-lg rounded-3xl p-6 sm:p-8" role="alert">
      <div className="grid size-12 place-items-center rounded-2xl border border-warn/30 bg-warn/10 text-warn">
        <Icon className="size-5" aria-hidden />
      </div>
      <h1 className="mt-5 text-2xl font-semibold text-ink">{title}</h1>
      <div className="mt-3 space-y-3 text-sm leading-relaxed text-ink-soft">{body}</div>
      <Button variant="glass" className="mt-6" onClick={onRetry}>
        Check again
      </Button>
    </div>
  )
}

interface AdminProps {
  theme: Theme
  onToggleTheme: () => void
}

/**
 * The administrator's page. No page links to it, and search engines are asked not
 * to list it, but its address is not a secret and not what protects it: every
 * request behind it needs a signed-in session, which the API checks.
 */
export default function Admin({ theme, onToggleTheme }: AdminProps) {
  const admin = useAdmin()
  const { view } = admin

  useEffect(() => {
    const previous = document.title
    document.title = `Admin — ${BRAND}`
    const meta = document.createElement('meta')
    meta.name = 'robots'
    meta.content = 'noindex, nofollow'
    document.head.append(meta)
    window.scrollTo({ top: 0, behavior: 'instant' })
    return () => {
      document.title = previous
      meta.remove()
    }
  }, [])

  const session = view.name === 'panel' || view.name === 'password' ? view.session : null

  let content: ReactNode
  switch (view.name) {
    case 'boot':
      content = (
        <p role="status" className="flex items-center justify-center gap-2.5 text-sm text-ink-mute">
          <LoaderCircle className="size-4 animate-spin" aria-hidden />
          Connecting to the API…
        </p>
      )
      break
    case 'unavailable':
      content = <UnavailableCard view={view} onRetry={admin.retry} />
      break
    case 'login':
      content = <SignIn notice={view.notice} onSignIn={admin.signIn} />
      break
    case 'password':
      content = (
        <div className="glass glow-border mx-auto w-full max-w-xl rounded-3xl p-6 sm:p-8">
          <PasswordForm email={view.session.email} forced onSubmit={admin.changePassword} />
        </div>
      )
      break
    case 'panel':
      content = <Panel session={view.session} admin={admin} />
      break
  }

  return (
    <AdminFrame theme={theme} onToggleTheme={onToggleTheme} email={session?.email ?? null} onSignOut={() => void admin.signOut()}>
      {view.name === 'panel' ? content : <div className="grid min-h-[60dvh] place-items-center py-6">{content}</div>}
    </AdminFrame>
  )
}
