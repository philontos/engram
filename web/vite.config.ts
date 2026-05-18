import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

// Local dev proxies API paths to the FastAPI server on :18080.
// All paths here MUST stay in sync with the prefixes registered in api/app/main.py.
const API_PROXIES = ['/capture', '/import', '/entries', '/query', '/ui/api', '/health']

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(
      API_PROXIES.map((p) => [p, { target: 'http://localhost:18080', changeOrigin: true }])
    ),
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
})
