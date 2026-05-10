// Machine-readable live inventory + capacity. Built at build time;
// re-fetched on every Pages deploy. Mirrors what the on-site assistant
// sees and lets external AI agents reason about availability without scraping.
import type { APIRoute } from 'astro';
import { getCapacity, getInventory } from '../../lib/sandbox';

export const GET: APIRoute = async () => {
  const [inventory, capacity] = await Promise.all([getInventory(), getCapacity()]);
  return new Response(JSON.stringify({
    inventory,
    capacity,
    note: "Inventory and capacity are simulator state from sandbox MCP. Re-fetched on every site build.",
  }, null, 2), {
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=60',
      'Access-Control-Allow-Origin': '*',
    },
  });
};
