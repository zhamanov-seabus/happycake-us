// Machine-readable cake configurator. POST a few simple parameters and
// get back a structured recommendation. Lets an external AI agent reach
// order intent without scraping the HTML form on /custom/.
//
// POST body:
//   {
//     occasion?: string,    // birthday | anniversary | office | walk-in | …
//     people?:   number,    // approximate guest count
//     dietary?:  string[],  // ['nut-free','vegetarian',…]
//     theme?:    string,    // free-form description
//     pickup_at?: string,   // ISO 8601 (optional)
//   }
//
// Response:
//   {
//     recommended_variation_id, slug, display_name,
//     price_usd, weight, lead_time_minutes,
//     allergen_warning, requires_owner_approval,
//     channels: { website_chat, custom_form, whatsapp },
//     next_step: "POST /chat to <wrapper> with the message field, or open <slug>"
//   }
//
// This endpoint is GET-only on the static site (Pages can't run server code),
// so we expose it as a GET that returns the schema + selection rules.
// Live recommendations are produced by the wrapper's /chat endpoint, which
// the agent grounds in catalog + brandbook.
import type { APIRoute } from 'astro';
import { getCatalog } from '../../lib/catalog';

export const GET: APIRoute = ({ url }) => {
  const catalog = getCatalog();

  // Pull selection inputs from query params; this is "GET as POST" on Pages.
  const params = url.searchParams;
  const people = Number(params.get('people') || 0);
  const occasion = (params.get('occasion') || '').toLowerCase();
  const dietary = (params.get('dietary') || '').toLowerCase().split(',').filter(Boolean);
  const theme = params.get('theme') || '';
  const pickupAt = params.get('pickup_at') || null;

  // Selection logic (deterministic; mirrors the agent's own reasoning).
  function recommend() {
    if (occasion === 'birthday' || theme) {
      return catalog.products.find(p => p.slug === 'custom-birthday-cake');
    }
    if (occasion === 'office' || people >= 12) {
      return catalog.products.find(p => p.slug === 'office-dessert-box');
    }
    if (people >= 6) {
      return catalog.products.find(p => p.slug === 'whole-honey-cake');
    }
    return catalog.products.find(p => p.slug === 'honey-cake-slice');
  }

  const product = recommend()!;
  const allergenWarning = dietary.includes('nut-free') && (product.allergens?.contains.includes('tree_nuts') || product.allergens?.traces.includes('tree_nuts'))
    ? "This product is made in a kitchen that handles tree nuts; flag your nut-free requirement so the team can confirm before accepting."
    : null;

  return new Response(JSON.stringify({
    inputs: { occasion, people, dietary, theme, pickup_at: pickupAt },
    recommended: {
      variation_id: product.variation_id,
      slug: product.slug,
      display_name: product.display_name,
      name: product.name,
      price_usd: product.price_usd,
      weight: product.weight,
      lead_time_minutes: product.lead_time_minutes ?? null,
      requires_owner_approval: Boolean(product.requires_owner_approval),
      allergens: product.allergens ?? null,
      allergen_warning: allergenWarning,
      url: `https://happycake.us/product/${product.slug}/`,
    },
    next_step: {
      preferred: "POST { message: '<order intent in plain English>', visitor_id: '<your-id>' } to the wrapper's /chat endpoint. The agent will confirm and queue an owner-approval card.",
      alternative: `Open https://happycake.us/product/${product.slug}/ and tap "Order this cake".`,
      custom_intake: "https://happycake.us/custom/",
    },
    schema: {
      query_params: {
        occasion: "string — birthday | anniversary | office | walk-in",
        people: "number — approximate guest count",
        dietary: "comma-separated — nut-free | vegetarian | dairy-free",
        theme: "string — free-form (triggers custom-cake routing if non-empty)",
        pickup_at: "ISO 8601",
      },
    },
  }, null, 2), {
    headers: {
      'Content-Type': 'application/json; charset=utf-8',
      'Cache-Control': 'public, max-age=60',
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
    },
  });
};
