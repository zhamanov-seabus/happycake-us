// Machine-readable policies. Agents read this without scraping the HTML
// FAQ at /policies/. Sourced from data/policies.yml at build time.
import type { APIRoute } from 'astro';
import yaml from 'js-yaml';
import { readFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const POLICIES_PATH = resolve(here, '../../../../data/policies.yml');

export const GET: APIRoute = () => {
  const data = yaml.load(readFileSync(POLICIES_PATH, 'utf-8'));
  return new Response(JSON.stringify(data, null, 2), {
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=60',
      'Access-Control-Allow-Origin': '*',
    },
  });
};
