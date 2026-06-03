import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiBaseUrl = env.VITE_API_BASE_URL || '/api'

  return {
    plugins: [vue()],
    server: {
      host: '0.0.0.0',
      port: 5173,
      proxy: apiBaseUrl.startsWith('/api')
        ? {
            '/api': {
              target: env.VITE_PROXY_TARGET || 'http://127.0.0.1:8080',
              changeOrigin: true
            }
          }
        : undefined
    }
  }
})
