/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the Lumora API, without a trailing slash. Empty in development. */
  readonly VITE_API_BASE_URL?: string
  /** Optional contact address shown in the footer and legal pages. */
  readonly VITE_CONTACT_EMAIL?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
