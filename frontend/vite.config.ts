import path from 'node:path'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss()],
  // https is added in front of this server (see start-servers.ps1 in the user's .operation-agents folder), so this stays plain http.
  // host: true listens on the network too, so the app can be opened at this computer's LAN address
  // (e.g. http://192.168.10.48:5180). The API's development CORS rule already allows that origin.
  server: { host: true, port: 5180, strictPort: true, allowedHosts: ['operational-agent.duckdns.org'] },
  resolve: {
    alias: { '@': path.resolve(import.meta.dirname, 'src') },
  },
})
