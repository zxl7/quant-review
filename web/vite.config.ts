import { defineConfig } from 'vite';
import vue from '@vitejs/plugin-vue';
import { viteSingleFile } from 'vite-plugin-singlefile';

export default defineConfig({
  plugins: [vue(), viteSingleFile()],
  server: {
    host: '0.0.0.0',
    port: 5188,
    fs: {
      allow: ['..'],
    },
  },
});
