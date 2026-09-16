import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// A dev szerver a backendre proxyzza az API/OCPP/OCPI útvonalakat, így a frontend
// relatív fetch("/api/...") hívásai fejlesztésben is ugyanúgy mennek, mint élesben.
// A cél a docker-compose.dev.yml-ből jön (http://backend:8000), enélkül localhost:8000.
const target = process.env.VITE_PROXY_TARGET || 'http://localhost:8000'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/api': target,
      '/ocpi': target,
      '/ocpp': { target, ws: true },
    },
  },
})
