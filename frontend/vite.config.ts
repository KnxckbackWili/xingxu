import { defineConfig, loadEnv } from 'vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'

// https://vitejs.dev/config/
export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, '.', '')
  const apiTarget = env.VITE_API_PROXY_TARGET || 'http://localhost:8000'

  return {
  plugins: [
    react(),
    VitePWA({
      strategies: 'injectManifest',
      registerType: 'autoUpdate',
      srcDir: 'src',
      filename: 'sw.js',
      includeAssets: ['xingxu-favicon-16.png', 'xingxu-favicon-32.png', 'xingxu-apple-touch-icon.png', 'xingxu-icon-192.png', 'xingxu-icon-512.png', 'xingxu-maskable-192.png', 'xingxu-maskable-512.png'],
      manifest: {
        name: '行序 · 项目工作台',
        short_name: '行序',
        description: '让项目，有序向前。面向 AGV 实施团队的项目工作台。',
        theme_color: '#176bfa',
        background_color: '#ffffff',
        display: 'standalone',
        lang: 'zh-CN',
        start_url: '/',
        icons: [
          { src: '/xingxu-icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/xingxu-icon-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/xingxu-maskable-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/xingxu-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
        shortcuts: [
          { name: '新建项目', short_name: '新建', description: '创建一个新的 AGV 实施项目', url: '/pm/projects?create=1' },
          { name: '数据总览', short_name: '总览', url: '/pm/dashboard' },
        ],
      },
      injectManifest: {
        globPatterns: ['**/*.{js,css,html,svg,png,ico,woff2}'],
        globIgnores: ['**/*.map', '**/charts-*.js'],
        maximumFileSizeToCacheInBytes: 5 * 1024 * 1024,
      },
    }),
  ],
  server: {
    port: 5173,
    proxy: {
      '/api': {
        target: apiTarget,
        changeOrigin: true,
      },
      '/health': {
        target: apiTarget,
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: 'dist',
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        manualChunks(id) {
          if (id.includes('node_modules/react') || id.includes('node_modules/zustand')) {
            return 'react'
          }
          if (id.includes('node_modules/echarts') || id.includes('node_modules/zrender')) {
            return 'charts'
          }
        },
      },
    },
  },
  }
})
