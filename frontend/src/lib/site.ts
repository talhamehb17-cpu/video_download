/** Site-wide constants. */

export const BRAND = 'Lumora'

export const REPOSITORY_URL = 'https://github.com/talhamehb17-cpu/video_download'

const contactEmail = (import.meta.env.VITE_CONTACT_EMAIL ?? '').trim()

/** Contact goes to the configured address, or to the public issue tracker. */
export const CONTACT = contactEmail
  ? { href: `mailto:${contactEmail}`, label: contactEmail, external: false }
  : { href: `${REPOSITORY_URL}/issues`, label: 'Open an issue on GitHub', external: true }

export const NAV_LINKS = [
  { id: 'top', label: 'Home', to: '/#top' },
  { id: 'features', label: 'Features', to: '/#features' },
  { id: 'how-it-works', label: 'How It Works', to: '/#how-it-works' },
  { id: 'faq', label: 'FAQ', to: '/#faq' },
] as const

/** Friendly names for domains on the service's allow list. */
const SOURCE_NAMES: Record<string, string> = {
  'archive.org': 'Internet Archive',
  'wikimedia.org': 'Wikimedia Commons',
  'nasa.gov': 'NASA',
  'media.ccc.de': 'media.ccc.de',
  'blender.org': 'Blender',
  'ted.com': 'TED',
  'vimeo.com': 'Vimeo',
}

export function sourceName(domain: string): string {
  return SOURCE_NAMES[domain] ?? domain
}

export function listSources(domains: string[]): string {
  return [...domains].map(sourceName).sort((a, b) => a.localeCompare(b)).join(' · ')
}
