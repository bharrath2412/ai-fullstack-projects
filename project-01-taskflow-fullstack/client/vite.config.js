import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5173,
    // Allow tunnelled preview hosts (Codespaces, E2B, ngrok, ...). In a plain
    // local setup this is a no-op; tighten it to an explicit list if you need to.
    allowedHosts: true,
    // Dev-time proxy: the browser only ever talks to :5173, Vite forwards
    // /api to the Express server. Keeps cookies/CORS simple.
    proxy: {
      '/api': {
        target: process.env.VITE_API_TARGET ?? 'http://localhost:4000',
        changeOrigin: true,
      },
    },
  },
  build: { outDir: 'dist', sourcemap: true },
});
