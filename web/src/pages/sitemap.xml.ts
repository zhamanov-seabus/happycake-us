import type { APIRoute } from 'astro';
import { getCatalog } from '../lib/catalog';

export const GET: APIRoute = ({ site }) => {
  const root = site?.toString().replace(/\/$/, '') ?? 'https://happycake.us';
  const basePath = (import.meta.env.BASE_URL ?? '/').replace(/\/$/, '');
  const base = root + basePath;
  const catalog = getCatalog();
  const urls = [
    `${base}/`,
    `${base}/catalog/`,
    `${base}/custom/`,
    `${base}/policies/`,
    `${base}/about/`,
    `${base}/order-status/`,
    `${base}/franchise/`,
    ...catalog.products.map(p => `${base}/product/${p.slug}/`),
  ];
  const xml = `<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n${urls
    .map(u => `  <url><loc>${u}</loc></url>`)
    .join('\n')}\n</urlset>\n`;
  return new Response(xml, {
    headers: { 'Content-Type': 'application/xml; charset=utf-8' },
  });
};
