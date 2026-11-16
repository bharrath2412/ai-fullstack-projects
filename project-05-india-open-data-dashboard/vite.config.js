import { defineConfig } from 'vitest/config';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '0.0.0.0',
    port: 5300,
    allowedHosts: true,
  },
  preview: { host: '0.0.0.0', port: 5300, allowedHosts: true },
  build: {
    outDir: 'dist',
    target: 'es2020',
    sourcemap: true,
    rollupOptions: {
      output: {
        // Keep the shell tiny: React in one chunk, app code in another.
        manualChunks: { react: ['react', 'react-dom'] },
      },
    },
  },
  test: {
    environment: 'node',
    include: ['tests/**/*.test.{js,jsx}'],
  },
});
