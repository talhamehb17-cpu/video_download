import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv } from 'vite'

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  // In development the browser talks to the API through this proxy, so the app
  // works from any host (including remote previews) without CORS set-up.
  const proxy = {
    '/api': { target: env.DEV_API_PROXY_TARGET || 'http://127.0.0.1:8000', changeOrigin: true },
  }
  const allowedHosts = ['.e2b.app']

  return {
    plugins: [react(), tailwindcss()],
    server: { host: '0.0.0.0', port: 5173, strictPort: true, allowedHosts, proxy },
    preview: { host: '0.0.0.0', port: 4173, strictPort: true, allowedHosts, proxy },
    build: { target: 'es2022', sourcemap: false, cssMinify: true },
    test: { environment: 'node', include: ['src/**/*.test.ts'] },
  }
})
