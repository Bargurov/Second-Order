/// <reference types="vite/client" />

// Typed access to the build-time env vars this app understands.
// Keep in sync with frontend/.env.example — every var documented
// there must be declared here so consumers get autocomplete and
// type-checked access via `import.meta.env`.
interface ImportMetaEnv {
  /** Optional override for the API base URL.  Empty / unset means
   *  same-origin `/api` (works with the Vite dev proxy locally and
   *  with a reverse-proxy rewrite in production). */
  readonly VITE_API_BASE_URL?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
