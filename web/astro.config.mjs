import { defineConfig } from 'astro/config';

export default defineConfig({
  site: 'https://happycake.us',
  output: 'static',
  build: {
    format: 'directory',
  },
});
