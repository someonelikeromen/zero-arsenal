import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { fileURLToPath } from 'node:url'
import { dirname, resolve } from 'node:path'

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..')

function backendProxyTarget(env: Record<string, string>): string {
  const port = env.PORT || '8001'
  const host = env.HOST && env.HOST !== '0.0.0.0' ? env.HOST : 'localhost'
  return `http://${host}:${port}`
}

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, projectRoot, '')
  return {
    plugins: [react()],
    envDir: projectRoot,
    server: {
      port: 5173,
      proxy: {
        '/api': {
          target: backendProxyTarget(env),
          changeOrigin: true,
        },
      },
    },
  }
})
