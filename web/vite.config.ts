import path from 'node:path'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// The contract (types and fixtures) lives one level above web/.
const contract = path.resolve(import.meta.dirname, '../contract')

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: { alias: { '@contract': contract } },
  server: { fs: { allow: ['..'] } },
})
