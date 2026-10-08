import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// En desarrollo (npm run dev) la config y la API las sirve el agente en :8000.
const agent = 'http://localhost:8000'

export default defineConfig({
  plugins: [react()],
  server: { proxy: { '/crm': agent, '/config.js': agent } },
})
