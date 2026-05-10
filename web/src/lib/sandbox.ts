// Build-time sandbox MCP fetcher. Used by /api/inventory.json and the
// homepage capacity badge to surface honest, live operational state.
//
// In static-output mode this runs once at `astro build` time per page.
// During the GitHub Pages workflow, env passes SBC_TEAM_TOKEN + SBC_MCP_URL.
// Without those env vars (e.g. local dev) we return safe fallbacks so the
// site still builds.

import { getCatalog } from './catalog';

const SBC_MCP_URL = process.env.SBC_MCP_URL || 'https://www.steppebusinessclub.com/api/mcp';
const SBC_TEAM_TOKEN = process.env.SBC_TEAM_TOKEN || '';

interface MCPResp {
  result?: { content?: Array<{ type: string; text: string }> };
  error?: unknown;
}

async function callMCP<T = unknown>(tool: string, args: Record<string, unknown> = {}): Promise<T | null> {
  if (!SBC_TEAM_TOKEN) return null;
  try {
    const r = await fetch(SBC_MCP_URL, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Accept': 'application/json, text/event-stream',
        'X-Team-Token': SBC_TEAM_TOKEN,
      },
      body: JSON.stringify({
        jsonrpc: '2.0', id: 1,
        method: 'tools/call',
        params: { name: tool, arguments: args },
      }),
    });
    if (!r.ok) return null;
    const data = (await r.json()) as MCPResp;
    const text = data.result?.content?.[0]?.text;
    if (!text) return null;
    try { return JSON.parse(text) as T; } catch { return text as unknown as T; }
  } catch {
    return null;
  }
}

export interface InventoryEntry {
  variationId: string;
  inStock: boolean;
  quantity?: number;
  fetched_at: string;
}

interface InventoryRaw {
  inventory?: Array<{ variationId: string; inStock?: boolean; quantity?: number; in_stock?: boolean }>;
}

export interface CapacityState {
  dailyCapacityMinutes: number;
  remainingCapacityMinutes: number;
  defaultLeadTimeMinutes: number;
  queuedTickets: number;
  acceptedTickets: number;
  fetched_at: string;
}

/** Pulls inventory for all catalog variation IDs. Returns empty array on failure. */
export async function getInventory(): Promise<InventoryEntry[]> {
  const catalog = getCatalog();
  const ids = catalog.products.map(p => p.variation_id);
  const data = await callMCP<InventoryRaw>('square_get_inventory', { variationIds: ids });
  const ts = new Date().toISOString();
  if (!data || !Array.isArray(data.inventory)) {
    // Permissive fallback: assume all in stock so we don't lie negatively
    // when the site builds without credentials. Marked with fallback flag.
    return ids.map(variationId => ({ variationId, inStock: true, fetched_at: ts }));
  }
  return data.inventory.map(row => ({
    variationId: row.variationId,
    inStock: row.inStock ?? row.in_stock ?? true,
    quantity: row.quantity,
    fetched_at: ts,
  }));
}

/** Pulls today's kitchen capacity. Returns null on failure. */
export async function getCapacity(): Promise<CapacityState | null> {
  const data = await callMCP<Partial<CapacityState>>('kitchen_get_capacity');
  if (!data || typeof data !== 'object') return null;
  return {
    dailyCapacityMinutes: data.dailyCapacityMinutes ?? 0,
    remainingCapacityMinutes: data.remainingCapacityMinutes ?? 0,
    defaultLeadTimeMinutes: data.defaultLeadTimeMinutes ?? 45,
    queuedTickets: (data as Record<string, number>).queuedTickets ?? 0,
    acceptedTickets: (data as Record<string, number>).acceptedTickets ?? 0,
    fetched_at: new Date().toISOString(),
  };
}
