import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import path from 'path'

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: { '@': path.resolve(__dirname, 'src') },
  },
  server: {
    port: 5173,
    proxy: {
      '/ui/api':  'http://localhost:18080',
      '/capture': 'http://localhost:18080',
      '/entries': 'http://localhost:18080',
      '/query':   'http://localhost:18080',
      '/import':  'http://localhost:18080',
      '/health':  'http://localhost:18080',
    },
  },
  build: {
    outDir: '../static',
    emptyOutDir: true,
  },
})
