/// <reference types="vitest" />
import { fileURLToPath, URL } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const PROXY = {
  '/api': { target: 'http://127.0.0.1:8000', changeOrigin: true },
  '/ws': { target: 'ws://127.0.0.1:8000', ws: true },
};

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: { '@': fileURLToPath(new URL('./src', import.meta.url)) },
  },
  // The backend enforces entitlements; the proxy just avoids CORS. Declared for both
  // `dev` and `preview` because the E2E suite runs against the *built* app, and a
  // proxy that only exists in dev would make the end-to-end test a different app.
  server: { port: 5173, proxy: PROXY },
  preview: { port: 4173, proxy: PROXY },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.ts'],
    include: ['src/**/*.test.{ts,tsx}'],
    css: true,
  },
});
