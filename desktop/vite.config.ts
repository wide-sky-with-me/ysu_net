import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
  plugins: [svelte()],
  clearScreen: false,
  server: { host: '127.0.0.1', port: 1420, strictPort: true },
  preview: { host: '127.0.0.1', port: 1421, strictPort: true },
  build: { target: ['es2022', 'chrome105', 'safari15'] },
  // Palette contracts import raw CSS instead of Vitest's default empty CSS stubs.
  test: { include: ['src/**/*.test.ts'], environment: 'node', css: { include: [/(?:app|accents)\.css/] } },
});
