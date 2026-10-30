import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  optimizeDeps: {
    noDiscovery: true,
    include: [],
  },
  server: {
    proxy: {
      '/api': process.env.VITE_API_PROXY || 'http://127.0.0.1:8000',
    },
  },
  preview: {
    proxy: {
      '/api': process.env.VITE_API_PROXY || 'http://127.0.0.1:8000',
    },
  },
})
