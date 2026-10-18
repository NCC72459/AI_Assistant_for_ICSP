import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      // 所有 /stream、/conversations 等 API 请求代理到 FastAPI
      '/stream': {
        target: 'http://localhost:8000',
        changeOrigin: true
      },
      '/conversations': {
        target: 'http://localhost:8000',
        changeOrigin: true
      }
    }
  },
  build: {
    outDir: 'dist',
    // 构建产物输出到 frontend/dist，让 server.py 可以读取
  }
})
