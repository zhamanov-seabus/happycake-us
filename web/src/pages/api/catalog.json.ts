// Machine-readable catalog endpoint — agents read this without scraping HTML.
// Stable schema: { products: Product[], categories: Category[], business: Business }.
import type { APIRoute } from 'astro';
import { getCatalog } from '../../lib/catalog';

export const GET: APIRoute = () => {
  const catalog = getCatalog();
  return new Response(JSON.stringify(catalog, null, 2), {
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=60',
      'Access-Control-Allow-Origin': '*',
    },
  });
};
