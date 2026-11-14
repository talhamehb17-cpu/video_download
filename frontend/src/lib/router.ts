/** A tiny path router: three pages do not need a dependency. */
import { useEffect, useSyncExternalStore } from 'react'

const listeners = new Set<() => void>()

function subscribe(listener: () => void): () => void {
  listeners.add(listener)
  window.addEventListener('popstate', listener)
  return () => {
    listeners.delete(listener)
    window.removeEventListener('popstate', listener)
  }
}

function currentPath(): string {
  const path = window.location.pathname.replace(/\/+$/, '')
  return path === '' ? '/' : path
}

export function usePath(): string {
  return useSyncExternalStore(subscribe, currentPath, () => '/')
}

/** Go to `to` ("/privacy", "/#faq", "/"). */
export function navigate(to: string): void {
  const url = new URL(to, window.location.origin)
  const samePage = url.pathname === window.location.pathname
  if (!samePage || url.hash !== window.location.hash) {
    window.history.pushState(null, '', url.pathname + url.search + url.hash)
    listeners.forEach((listener) => listener())
  }
  // Moving within the page glides there now. Moving to another page is finished
  // by `usePageEntry` once that page is on screen (its sections do not exist yet).
  if (!samePage) return
  if (url.hash) document.getElementById(decodeURIComponent(url.hash.slice(1)))?.scrollIntoView({ behavior: 'smooth' })
  else window.scrollTo({ top: 0, behavior: 'smooth' })
}

let firstPage = true

/**
 * Call once in every page component. When the page appears it jumps to the
 * section named in the address ("/#faq"), or to the top. The very first page of a
 * visit is left alone unless it names a section, so a reload keeps its position.
 */
export function usePageEntry(): void {
  useEffect(() => {
    const first = firstPage
    firstPage = false
    const id = decodeURIComponent(window.location.hash.slice(1))
    const target = id ? document.getElementById(id) : null
    if (target) target.scrollIntoView({ behavior: 'instant', block: 'start' })
    else if (!first) window.scrollTo({ top: 0, behavior: 'instant' })
  }, [])
}
