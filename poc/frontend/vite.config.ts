// vitest 的 config 入口 —— 它比 vite 的多认一个 `test` 字段。
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { tanstackRouter } from '@tanstack/router-plugin/vite'
import path from 'node:path'

// New UI mounts at /v2 so the existing /static/index.html keeps working.
// Dev server proxies /api/* to the FastAPI gateway on :8000.
export default defineConfig({
  base: '/v2/',
  plugins: [
    /* 必须排在 react() 前面：它要先把 src/routes/ 扫成 routeTree.gen.ts，
       react 插件才有完整的模块图可编译。
       `autoCodeSplitting` 顶掉了原来 App.tsx 里那 18 个手写的 `lazy(() =>
       import(...).then(m => ({ default: m.X })))` —— 每条路由的组件照样是单独
       一个 chunk，但不用再逐个包一层。 */
    tanstackRouter({ target: 'react', autoCodeSplitting: true }),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      '@': path.resolve(__dirname, './src'),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8000',
        changeOrigin: false,
      },
    },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
  },
  test: {
    /*
     * 单测只收 src 下本仓自己的用例。
     *
     * `e2e/**`：playwright 的 spec，vitest 收进来只会在 import 阶段炸掉。长期显示
     * 成「Test Files 9 failed」，是个假信号，读的人得先学会忽略它。
     */
    exclude: ['node_modules/**', 'dist/**', 'e2e/**'],
  },
})
