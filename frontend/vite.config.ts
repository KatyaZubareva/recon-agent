import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// В разработке /api проксируется на backend (uvicorn на :8000);
// в Compose собранная страница раздаётся самим FastAPI.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: { '/api': 'http://localhost:8000' },
  },
})
