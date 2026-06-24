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
      // All /api requests forwarded to FastAPI — no CORS issues in dev.
      // Honors VITE_API_TARGET (see README); defaults to 8765 because Hyper-V
      // reserves 8000/8001 on Windows, so the backend runs on 8765.
      '/api': {
        target: process.env.VITE_API_TARGET || 'http://localhost:8765',
        changeOrigin: true,
      },
    },
  },
})
