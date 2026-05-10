import { defineConfig } from 'astro/config';

// On GitHub Pages we deploy at /happycake-us/ subpath. PUBLIC_SITE_BASE
// can be overridden to '/' for root deploys (Vercel/Netlify/Cloudflare Pages
// or a custom domain on Pages).
export default defineConfig({
  site: process.env.PUBLIC_SITE_URL ?? 'https://zhamanov-seabus.github.io',
  base: process.env.PUBLIC_SITE_BASE ?? '/happycake-us',
  output: 'static',
  build: {
    format: 'directory',
  },
});
