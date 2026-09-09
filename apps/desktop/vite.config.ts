import { fileURLToPath, URL } from 'node:url';
import react from '@vitejs/plugin-react';
import { defineConfig } from 'vite';

const sharedSrc = fileURLToPath(new URL('../../packages/shared/src', import.meta.url));
const repoRoot = fileURLToPath(new URL('../..', import.meta.url));

export default defineConfig({
  plugins: [react()],
  // Relative asset paths so Electron can load the build from file://.
  base: './',
  resolve: {
    alias: {
      '@viksitgaanw/shared': sharedSrc,
    },
  },
  server: {
    // Pinned to IPv4 loopback on purpose. The default 'localhost' resolves to
    // ::1 first on Windows, which leaves nothing listening on 127.0.0.1 -- so
    // the `wait-on tcp:127.0.0.1:5273` gate in `dev:electron` never opens and
    // Electron never starts. Loopback-only also matches the app's threat
    // model: nothing here should be reachable from the network.
    host: '127.0.0.1',
    port: 5273,
    strictPort: true,
    // The shared package lives outside this app's root.
    fs: { allow: [repoRoot] },
  },
  build: {
    outDir: 'dist',
    emptyOutDir: true,
    sourcemap: true,
  },
});
