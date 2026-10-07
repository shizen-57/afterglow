import {defineConfig} from 'vite';
import react from '@vitejs/plugin-react';
import tailwindcss from '@tailwindcss/vite';
import {fileURLToPath,URL} from 'node:url';
export default defineConfig({plugins:[react(),tailwindcss()],resolve:{alias:{'@':fileURLToPath(new URL('./src',import.meta.url))}},build:{chunkSizeWarningLimit:1300,rollupOptions:{output:{manualChunks(id){if(id.includes('/maplibre-gl/'))return 'maplibre';}}}}});
