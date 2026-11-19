import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    strictPort: true,
    // 页面里只写 /api/...，由开发服务器转给后端，浏览器看来是同源，不会有跨域问题
    proxy: {
      '/api': 'http://127.0.0.1:8000',
    },
  },
})
