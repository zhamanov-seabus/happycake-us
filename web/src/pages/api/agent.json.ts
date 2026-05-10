// Machine-readable index of every wrapper JSON-RPC the assistant exposes.
// Agent crawlers read this without parsing README — schema, examples, and
// purpose for each endpoint. Extends llms.txt for programmatic discovery.
import type { APIRoute } from 'astro';

const WRAPPER_BASE = import.meta.env.PUBLIC_WRAPPER_URL ?? 'http://localhost:8000';

const spec = {
  $schema: 'https://happycake.us/api/agent.schema.json',
  description: 'JSON-RPC catalogue for HappyCake — every endpoint the on-site assistant or an external agent can call.',
  generatedAt: new Date().toISOString(),
  base_url: WRAPPER_BASE,
  closing_pattern: 'Replies should remain in HappyCake voice; brand rules at /llms.txt and full brandbook at /api/policies.json.',
  endpoints: [
    {
      path: '/chat',
      method: 'POST',
      purpose: 'Customer-facing chat. Returns a JSON decision (intent, reply, items, order_id) and triggers owner Telegram handoff or auto-confirm side effects.',
      input: {
        message: 'string — what the customer typed',
        visitor_id: 'string | null — opaque per-browser id for memory continuity',
        history: 'Array<{role: "user"|"assistant", text: string}> | null — last few turns for multi-turn context',
      },
      output: {
        reply: 'string — assistant text',
        intent: '"faq" | "order_intent" | "complaint" | "escalate" | "smalltalk"',
        needs_owner_approval: 'boolean',
        order_id: 'string | null — present when an order card was created',
      },
      example_request: { message: 'whole honey cake for 4pm today', visitor_id: 'web-abc' },
      rate_limit: '20 requests / minute / IP',
    },
    {
      path: '/configure',
      method: 'POST',
      purpose: 'Submit a custom-cake intake form. Validates fields, fires an owner approval card, returns the order_id used to subscribe to status events.',
      input: {
        flavour: 'string — one of: honey | pistachio | napoleon | other',
        size_kg: 'number — 1.0 to 3.0',
        servings: 'integer — 6 to 30',
        pickup_iso: 'ISO 8601 datetime — must be ≥ 3h from now',
        decoration_brief: 'string — free text, max 500 chars',
        allergies: 'string[] — any of: dairy, egg, wheat, tree_nuts, soy, none',
        contact_name: 'string',
        contact_phone: 'string E.164 or US formatted',
      },
      output: {
        ok: 'boolean',
        order_id: 'string | null',
        message: 'string',
      },
      example_request: {
        flavour: 'honey',
        size_kg: 1.5,
        servings: 12,
        pickup_iso: '2026-05-13T15:00:00-05:00',
        decoration_brief: 'For Maya turning 6, no nuts on top',
        allergies: ['tree_nuts'],
        contact_name: 'Maria',
        contact_phone: '+12815550199',
      },
    },
    {
      path: '/franchise',
      method: 'POST',
      purpose: 'Texas-only franchise inquiry. Validates six required fields, logs to evidence, FYI to owner Telegram, returns a tracking handle.',
      input: {
        name: 'string',
        email: 'string',
        phone: 'string',
        city: 'string — Texas city or metro',
        capital: '"250-400k" | "400-600k" | "600k+" | "raising"',
        timeline: '"0-3mo" | "3-6mo" | "6-12mo" | "exploring"',
        message: 'string | null — optional context',
      },
      output: {
        ok: 'boolean',
        message: 'string',
        fields: 'string[] | null — names of fields that failed validation',
      },
      rate_limit: '5 requests / minute / IP',
    },
    {
      path: '/lead',
      method: 'POST',
      purpose: 'Generic lead-capture endpoint for marketing redirects. Routes to marketing_route_lead in the sandbox MCP.',
      input: {
        source: 'string — campaign id or utm_source',
        contact: 'string — phone, email, or social handle',
        note: 'string | null',
      },
      output: { ok: 'boolean', lead_id: 'string | null' },
    },
    {
      path: '/order/{order_id}',
      method: 'GET',
      purpose: 'Polling-friendly order status. Returns current status + history of state changes. Used by the chat widget instead of SSE because Cloudflare quick tunnels buffer event streams.',
      input: { order_id: 'string — the hc_… id returned by /chat' },
      output: {
        order_id: 'string',
        status: '"pending" | "approved" | "rejected" | "edit" | "edit_followup"',
        history: 'Array<{ts, status, message?}>',
      },
    },
    {
      path: '/health',
      method: 'GET',
      purpose: 'Liveness probe. Returns wrapper status and the configured tunnel URL.',
      output: { ok: 'boolean', tunnel: 'string' },
    },
  ],
  related_resources: {
    catalog: '/api/catalog.json',
    policies: '/api/policies.json',
    inventory: '/api/inventory.json',
    configure_schema: '/api/configure.json',
    sitemap: '/sitemap.xml',
    llms_guide: '/llms.txt',
  },
};

export const GET: APIRoute = () => new Response(JSON.stringify(spec, null, 2), {
  headers: {
    'Content-Type': 'application/json; charset=utf-8',
    'Cache-Control': 'public, max-age=300',
    'Access-Control-Allow-Origin': '*',
  },
});
