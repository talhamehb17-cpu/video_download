/** Site-wide constants. */

export const BRAND = 'Lumora'

export const REPOSITORY_URL = 'https://github.com/talhamehb17-cpu/video_download'

const contactEmail = (import.meta.env.VITE_CONTACT_EMAIL ?? '').trim()

/** Contact goes to the configured address, or to the public issue tracker. */
export const CONTACT = contactEmail
  ? { href: `mailto:${contactEmail}`, label: contactEmail, external: false }
  : { href: `${REPOSITORY_URL}/issues`, label: 'Open an issue on GitHub', external: true }

/**
 * Where the administrator's page lives. Nothing links to it and search engines
 * are told to skip it, but it is not a secret (this file is public): what protects
 * the panel is the sign-in the API demands, not the address.
 */
export const ADMIN_PATH = '/devzardhft'

export const NAV_LINKS = [
  { id: 'top', label: 'Home', to: '/#top' },
  { id: 'features', label: 'Features', to: '/#features' },
  { id: 'platforms', label: 'Platforms', to: '/#platforms' },
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
  // The space before each dot does not break, so a wrapped line never starts with a dot.
  return [...domains].map(sourceName).sort((a, b) => a.localeCompare(b)).join('\u00a0· ')
}
