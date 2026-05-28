import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import path from 'path'

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': path.resolve(__dirname, './src') },
  },
  server: {
    port: 5173,
    proxy: {
      // All /api requests forwarded to FastAPI — no CORS issues in dev
      '/api': {
        // Default to port 8001 — port 8000 is reserved by Windows on this machine
        // (WinError 10013). Override via VITE_API_TARGET if you bind elsewhere.
        target: process.env.VITE_API_TARGET ?? 'http://localhost:8001',
        changeOrigin: true,
      },
    },
  },
})
