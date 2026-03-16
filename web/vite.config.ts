import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: '../src/crew/gateway/static',
    emptyOutDir: true,
  },
  server: {
    proxy: {
      '/tasks': 'http://localhost:8080',
      '/gates': 'http://localhost:8080',
      '/health': 'http://localhost:8080',
      '/stream': 'http://localhost:8080',
    },
  },
})
