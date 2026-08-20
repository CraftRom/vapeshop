import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  // Застосунок віддається за адресою /app, тож шляхи до ассетів мають
  // будуватися від неї, інакше Telegram запитає їх від кореня і отримає 404.
  base: '/app/',
  build: { outDir: 'dist', sourcemap: false },
})
