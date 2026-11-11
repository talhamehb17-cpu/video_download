import { AnimatePresence, LazyMotion, MotionConfig, domAnimation, m } from 'framer-motion'
import { Suspense, lazy, useCallback, useState } from 'react'

import { Background } from './components/layout/Background'
import { Footer } from './components/layout/Footer'
import { Navbar } from './components/layout/Navbar'
import { useServiceStatus } from './hooks/useServiceStatus'
import { useTheme } from './hooks/useTheme'
import { usePath } from './lib/router'
import Home from './pages/Home'

// The legal pages are rarely opened, so they load on demand.
const Privacy = lazy(() => import('./pages/Legal').then((module) => ({ default: module.Privacy })))
const Terms = lazy(() => import('./pages/Legal').then((module) => ({ default: module.Terms })))
const NotFound = lazy(() => import('./pages/Legal').then((module) => ({ default: module.NotFound })))

const PAGE_TRANSITION = { duration: 0.4, ease: [0.16, 1, 0.3, 1] as const }

export default function App() {
  const path = usePath()
  const { theme, toggle } = useTheme()
  const { state: service, retry } = useServiceStatus()
  const [activeSection, setActiveSection] = useState<string | null>(null)
  const onActiveSection = useCallback((id: string | null) => setActiveSection(id), [])
  const config = service.status === 'online' ? service.config : null

  let page
  if (path === '/') page = <Home service={service} onRetryService={retry} onActiveSection={onActiveSection} />
  else if (path === '/privacy') page = <Privacy config={config} />
  else if (path === '/terms') page = <Terms />
  else page = <NotFound />

  return (
    <LazyMotion features={domAnimation} strict>
      <MotionConfig reducedMotion="user">
        <a
          href="#main"
          className="bg-brand fixed left-4 top-4 z-[60] -translate-y-24 rounded-full px-4 py-2 text-sm font-medium text-white transition-transform focus:translate-y-0"
        >
          Skip to content
        </a>
        <Background />
        <Navbar theme={theme} onToggleTheme={toggle} activeSection={path === '/' ? activeSection : null} />
        <AnimatePresence mode="wait" initial={false}>
          <m.div
            key={path}
            initial={{ opacity: 0, y: 14 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            transition={PAGE_TRANSITION}
          >
            <Suspense fallback={<div className="min-h-dvh" />}>{page}</Suspense>
            <Footer />
          </m.div>
        </AnimatePresence>
      </MotionConfig>
    </LazyMotion>
  )
}
