import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
import { localOnly, proxyOptions } from './local-proxy.js';

export default defineConfig({
  plugins: [localOnly(), react()],
  envDir: false,
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true, cors: false,
    allowedHosts: ['localhost'], proxy: proxyOptions(),
    fs: { strict: true },
  },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true, cors: false, proxy: proxyOptions() },
});
