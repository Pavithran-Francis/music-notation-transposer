import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The backend runs on :8000 in development; /api is proxied so the app is same-origin.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
    },
  },
})
