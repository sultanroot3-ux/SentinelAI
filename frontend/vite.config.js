import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Backend origin used by both the dev server and the production-like `preview`
// server (the latter is what the Playwright E2E suite runs against). Override
// with VITE_API_TARGET when the backend is not on the default localhost:8000.
const apiTarget = process.env.VITE_API_TARGET || 'http://localhost:8000';

const proxy = {
  '/api': { target: apiTarget, changeOrigin: true },
  '/static': { target: apiTarget, changeOrigin: true },
};

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy,
  },
  // `vite preview` serves the built bundle (production-like) and, mirroring the
  // nginx reverse proxy in docker-compose.prod, forwards /api to the backend.
  preview: {
    port: 4173,
    proxy,
  },
});
